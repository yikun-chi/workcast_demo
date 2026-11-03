"""Export saved responses and browsable input records, or build the read-only site."""
from __future__ import annotations

import argparse
import hashlib
import gzip
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import re
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
TABLE_CHUNK_SIZE = 10_000


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=1) + "\n")


def export_table(path: Path, staging: Path, iid: str, metadata: dict, chunk_size: int = TABLE_CHUNK_SIZE, prefix: Path | None = None) -> dict:
    """Stream all normalized rows into deterministic compressed chunks, never a sample."""
    import pandas as pd
    import pyarrow.dataset as ds

    name = metadata["name"]
    prefix = prefix or Path("tables") / iid / hashlib.sha256(name.encode()).hexdigest()[:16]
    if path.suffix == ".csv":
        frame = pd.read_csv(path)
        frames = (frame.iloc[start:start + chunk_size] for start in range(0, len(frame), chunk_size))
    else:
        frames = (batch.to_pandas() for batch in ds.dataset(path, format="parquet", partitioning="hive").to_batches(batch_size=chunk_size))
    pending, chunks, total = [], [], 0

    def save(rows):
        relative = prefix / f"{len(chunks):05d}.json.gz"
        destination = staging / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(rows, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
        destination.write_bytes(gzip.compress(raw, compresslevel=6, mtime=0))
        chunks.append(relative.as_posix())

    for frame in frames:
        # Same timestamp, missing-value and numeric serialization as the table API.
        pending.extend(json.loads(frame[metadata["columns"]].to_json(orient="values", date_format="iso")))
        total += len(frame)
        while len(pending) >= chunk_size:
            save(pending[:chunk_size])
            del pending[:chunk_size]
    if pending:
        save(pending)
    if total != metadata["rows"]:
        raise ValueError(f"{iid}/{name}: row count changed during export")
    return {"name": name, "columns": metadata["columns"], "total": total, "chunk_size": chunk_size, "chunks": chunks}


def export_snapshot(destination: Path) -> None:
    # Import scientific dependencies only for refresh. CI builds from committed JSON.
    from fastapi.testclient import TestClient
    from orgsim.server.app import app, _ctx, _tables

    source_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    source_dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip())

    def get(client, path):
        response = client.get("/api" + path)
        response.raise_for_status()
        return response.json()

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix="snapshot-") as temp:
        staging = Path(temp)
        with TestClient(app) as client:
            instances = get(client, "/instances")
            occupations = {}
            for instance in instances:
                iid = instance["id"]
                responses = {}
                for route in ("", "/results", "/evaluation", "/insights", "/insights-summary", "/scenario-results", "/report", "/summary", "/tables",
                              "/scenarios", "/ontology/concepts", "/ontology/bindings", "/seats"):
                    responses[route or "/"] = get(client, f"/instances/{iid}{route}")
                if any(v.get("state") != "ready" for v in responses["/results"].get("explorations", [])):
                    raise ValueError(f"{iid}: refresh missing/stale alternative comparisons before publishing")
                # Preserve meaningful result timestamps instead of export-time API timestamps.
                responses["/results"]["generated"] = responses["/evaluation"].get("generated")
                responses["/runs"] = [{k: run[k] for k in ("scenario", "run_id", "complete")}
                                      for run in get(client, f"/instances/{iid}/runs")]
                for scenario in responses["/scenarios"]:
                    responses[f"/scenarios/{scenario['id']}"] = get(client, f"/instances/{iid}/scenarios/{scenario['id']}")
                for role in responses["/ontology/bindings"].get("roles", []):
                    code = role.get("onet_code")
                    if code and code not in occupations:
                        occupations[code] = get(client, f"/onet/occupations/{code}")
                evaluation = ROOT / "runs" / iid / "evaluation.json"
                paths = _tables(_ctx(iid))
                table_data = {}
                for table in responses["/tables"]:
                    if table.get("error"):
                        raise ValueError(f"{iid}: cannot publish unreadable table {table['name']}")
                    table_data[table["name"]] = export_table(paths[table["name"]], staging, iid, table)
                run_data = {}
                import pyarrow.parquet as pq
                for item in responses["/scenario-results"]:
                    run = item["run"]
                    if not run:
                        continue
                    sid, rid = run["scenario"], run["run_id"]
                    prefix = Path("runs") / iid / sid / rid
                    history = get(client, f"/instances/{iid}/runs/{sid}/{rid}/history")
                    relative = prefix / "history.json.gz"
                    target = staging / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(gzip.compress(json.dumps(history, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode(), compresslevel=6, mtime=0))
                    trace_path = ROOT / "runs" / iid / sid / rid / "trace.parquet"
                    trace = pq.ParquetFile(trace_path)
                    metadata = {"name": "trace", "columns": trace.schema_arrow.names, "rows": trace.metadata.num_rows}
                    run_data[f"{sid}/{rid}"] = {"history": relative.as_posix(), "trace": export_table(trace_path, staging, iid, metadata, prefix=prefix / "trace")}
                write_json(staging / f"{iid}.json", {"instance": iid, "evaluation_sha256": digest(evaluation),
                                                    "responses": responses, "tables": table_data, "run_data": run_data})
                print(f"Exported {iid}", flush=True)
        index = {"schema_version": 3, "captured_at": datetime.now(timezone.utc).isoformat(),
                 "source_commit": source_commit, "source_dirty": source_dirty,
                 "instances": instances, "occupations": occupations,
                 "files": {p.relative_to(staging).as_posix(): digest(p) for p in sorted(staging.rglob("*")) if p.is_file()}}
        write_json(staging / "index.json", index)
        validate_snapshot(staging)
        destination.mkdir(exist_ok=True)
        for directory in ("tables", "runs"):
            if (destination / directory).exists():
                shutil.rmtree(destination / directory)
        for path in staging.iterdir():
            path.replace(destination / path.name)
        for old in destination.glob("*.json"):
            if old.name != "index.json" and old.name not in index["files"]:
                old.unlink()


def validate_snapshot(source: Path) -> dict:
    index = json.loads((source / "index.json").read_text())
    if index.get("schema_version") != 3 or not index.get("instances"):
        raise ValueError("Unsupported or empty public snapshot")
    ids = [i["id"] for i in index["instances"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate instance IDs")
    expected_files = set()
    for iid in ids:
        if not iid.replace("_", "").isalnum():
            raise ValueError("Invalid instance ID")
        file = source / f"{iid}.json"
        expected_files.add(file.name)
        if digest(file) != index["files"].get(file.name):
            raise ValueError(f"Snapshot checksum mismatch: {file.name}")
        data = json.loads(file.read_text())
        for route in ("/", "/results", "/evaluation", "/insights", "/insights-summary", "/scenario-results", "/summary", "/scenarios", "/tables", "/ontology/concepts"):
            if route not in data["responses"]:
                raise ValueError(f"{iid}: missing {route}")
        metadata = {t["name"]: t for t in data["responses"]["/tables"]}
        if set(data.get("tables", {})) != set(metadata):
            raise ValueError(f"{iid}: missing table records")
        for name, table in data.get("tables", {}).items():
            if table["columns"] != metadata[name]["columns"] or table["total"] != metadata[name]["rows"]:
                raise ValueError(f"{iid}/{name}: table metadata mismatch")
            size = table["chunk_size"]
            if size <= 0 or len(table["chunks"]) != (table["total"] + size - 1) // size:
                raise ValueError(f"{iid}/{name}: incomplete table chunks")
            for number, relative in enumerate(table["chunks"]):
                if not re.fullmatch(rf"tables/{iid}/[0-9a-f]{{16}}/{number:05d}\.json\.gz", relative):
                    raise ValueError(f"Invalid table chunk path: {relative}")
                if relative in expected_files:
                    raise ValueError(f"Duplicate table chunk: {relative}")
                expected_files.add(relative)
                chunk = source / relative
                if chunk.is_symlink() or not chunk.resolve().is_relative_to(source.resolve()) or digest(chunk) != index["files"].get(relative):
                    raise ValueError(f"Snapshot checksum mismatch: {relative}")
                rows = json.loads(gzip.decompress(chunk.read_bytes()))
                expected_rows = min(size, table["total"] - number * size)
                if len(rows) != expected_rows or any(not isinstance(row, list) or len(row) != len(table["columns"]) for row in rows):
                    raise ValueError(f"Invalid table rows: {relative}")
        expected_runs = {f"{r['run']['scenario']}/{r['run']['run_id']}" for r in data["responses"]["/scenario-results"] if r.get("run")}
        if set(data.get("run_data", {})) != expected_runs:
            raise ValueError(f"{iid}: missing scenario histories")
        for key, run in data.get("run_data", {}).items():
            if not re.fullmatch(r"[a-z][a-z0-9_-]*/[A-Za-z0-9_-]+", key):
                raise ValueError("Invalid run key")
            prefix = f"runs/{iid}/{key}"
            if run["history"] != f"{prefix}/history.json.gz":
                raise ValueError("Invalid history path")
            table = run["trace"]
            size = table["chunk_size"]
            if size <= 0 or len(table["chunks"]) != (table["total"] + size - 1) // size:
                raise ValueError("Incomplete trace chunks")
            for number, relative in enumerate([run["history"], *table["chunks"]]):
                if number and relative != f"{prefix}/trace/{number-1:05d}.json.gz":
                    raise ValueError("Invalid trace path")
                if relative in expected_files:
                    raise ValueError("Duplicate run resource")
                expected_files.add(relative)
                path = source / relative
                if path.is_symlink() or not path.resolve().is_relative_to(source.resolve()) or digest(path) != index["files"].get(relative):
                    raise ValueError(f"Snapshot checksum mismatch: {relative}")
                value = json.loads(gzip.decompress(path.read_bytes()))
                if number:
                    if len(value) != min(size, table["total"] - (number-1)*size) or any(not isinstance(row, list) or len(row) != len(table["columns"]) for row in value):
                        raise ValueError("Invalid trace rows")
                elif f"{value['scenario']}/{value['run_id']}" != key or value["trace_rows"] != table["total"]:
                    raise ValueError("History identity or trace count mismatch")
    if set(index["files"]) != expected_files:
        raise ValueError("Unexpected files in public snapshot index")
    return index


def build_site(source: Path, output: Path) -> None:
    index = validate_snapshot(source)
    output = output.resolve()
    if output == ROOT or output.is_relative_to(ROOT / "ui") or output.is_relative_to(source.resolve()):
        raise ValueError("Build output must be separate from source files")
    if output.exists() and not (output / ".workcast-site").is_file():
        raise ValueError("Refusing to replace a directory that is not a generated WORKCAST site")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix="site-") as temp:
        staging = Path(temp) / "site"
        staging.mkdir()
        shutil.copytree(ROOT / "ui", staging / "ui", ignore=shutil.ignore_patterns("dev", "node_modules", "dist"))
        (staging / "public-data").mkdir()
        for name in ["index.json", *index["files"]]:
            (staging / "public-data" / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / name, staging / "public-data" / name)
        html = (ROOT / "ui/index.html").read_text().replace('"/ui/', '"ui/')
        html = html.replace("</head>", '<meta name="workcast-mode" content="static">\n</head>')
        (staging / "index.html").write_text(html)
        # The inner UI index is not another entry point; only the root shell is served.
        (staging / "ui/index.html").unlink()
        for instance in index["instances"]:
            iid = instance["id"]
            for plugin in instance.get("plugins", []):
                relative = Path(plugin["url"].lstrip("/"))
                expected = Path("instances") / iid / "ui"
                if not relative.is_relative_to(expected) or ".." in relative.parts or relative.suffix != ".html":
                    raise ValueError(f"Invalid plugin path: {relative}")
                destination = staging / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                plugin_html = (ROOT / relative).read_text().replace("</head>", '<meta name="workcast-mode" content="static">\n</head>')
                destination.write_text(plugin_html)
        (staging / ".nojekyll").touch()
        (staging / ".workcast-site").write_text("Generated from ui/ and public-data/.\n")
        if output.exists():
            shutil.rmtree(output)
        staging.replace(output)
    print(f"Built {len(index['instances'])} instances at {output}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("snapshot", "build", "check"))
    parser.add_argument("--snapshot", type=Path, default=ROOT / "public-data")
    parser.add_argument("--output", type=Path, default=ROOT / "build/site")
    args = parser.parse_args()
    if args.command == "snapshot":
        export_snapshot(args.snapshot)
    elif args.command == "build":
        build_site(args.snapshot, args.output)
    else:
        index = validate_snapshot(args.snapshot)
        print(f"Verified {len(index['instances'])} public snapshots")


if __name__ == "__main__":
    main()
