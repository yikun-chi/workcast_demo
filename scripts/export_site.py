"""Export saved aggregate responses, or build the read-only site without datasets."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=1) + "\n")


def export_snapshot(destination: Path) -> None:
    # Import scientific dependencies only for refresh. CI builds from committed JSON.
    from fastapi.testclient import TestClient
    from orgsim.server.app import app

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
                for route in ("", "/results", "/evaluation", "/insights", "/report", "/summary", "/tables",
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
                write_json(staging / f"{iid}.json", {"instance": iid, "evaluation_sha256": digest(evaluation), "responses": responses})
                print(f"Exported {iid}", flush=True)
        index = {"schema_version": 1, "captured_at": datetime.now(timezone.utc).isoformat(),
                 "source_commit": source_commit, "source_dirty": source_dirty,
                 "instances": instances, "occupations": occupations,
                 "files": {p.name: digest(p) for p in sorted(staging.glob("*.json"))}}
        write_json(staging / "index.json", index)
        destination.mkdir(exist_ok=True)
        for path in staging.iterdir():
            path.replace(destination / path.name)
        for old in destination.glob("*.json"):
            if old.name != "index.json" and old.name not in index["files"]:
                old.unlink()


def validate_snapshot(source: Path) -> dict:
    index = json.loads((source / "index.json").read_text())
    if index.get("schema_version") != 1 or not index.get("instances"):
        raise ValueError("Unsupported or empty public snapshot")
    ids = [i["id"] for i in index["instances"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate instance IDs")
    for iid in ids:
        if not iid.replace("_", "").isalnum():
            raise ValueError("Invalid instance ID")
        file = source / f"{iid}.json"
        if digest(file) != index["files"].get(file.name):
            raise ValueError(f"Snapshot checksum mismatch: {file.name}")
        data = json.loads(file.read_text())
        for route in ("/", "/results", "/evaluation", "/insights", "/summary", "/scenarios", "/tables", "/ontology/concepts"):
            if route not in data["responses"]:
                raise ValueError(f"{iid}: missing {route}")
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
        for name in ["index.json", *(f"{i['id']}.json" for i in index["instances"])]:
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
