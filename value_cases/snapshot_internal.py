"""Snapshot locally evaluated results without accessing an author's remote host."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

SOURCES = {
    "openrouter_evaluation.json": "runs/openrouter/evaluation.json",
    "ctrip_evaluation.json": "runs/ctrip/evaluation.json",
    "btos_ai_evaluation.json": "runs/btos_ai/evaluation.json",
    "so_chatgpt_evaluation.json": "runs/so_chatgpt/evaluation.json",
    "validation_trip_bpi19.md": "docs/validation.md",
    "trip_instance.yaml": "instances/trip/instance.yaml",
    "bpi19_no_expansion.yaml": "instances/bpi19/scenarios/no_expansion.yaml",
}


def snapshot(root: Path, destination: Path) -> list[dict]:
    missing = [source for source in SOURCES.values() if not (root / source).is_file()]
    if missing:
        raise FileNotFoundError("Build the local evaluations/reports before refreshing snapshots: " + ", ".join(missing))
    # Read all inputs before changing any existing sealed file. A missing or unreadable
    # source must not leave a mixture of old and new inputs.
    contents = {name: (root / source).read_bytes() for name, source in SOURCES.items()}
    manifest = []
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for name, source in sorted(SOURCES.items()):
        tracked = not source.startswith("runs/")
        commit = subprocess.run(["git", "log", "-1", "--format=%H", "--", source], cwd=root,
                                capture_output=True, text=True, check=True).stdout.strip() if tracked else None
        manifest.append({"file": name, "copied_from": source, "last_commit_of_original": commit,
                         "copied_utc": timestamp, "bytes": len(contents[name]),
                         "sha256": hashlib.sha256(contents[name]).hexdigest()})
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="snapshot-", dir=destination.parent) as staging:
        temporary = Path(staging)
        for name, data in contents.items():
            (temporary / name).write_bytes(data)
        (temporary / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
        for name in contents:
            (temporary / name).replace(destination / name)
        # Publish the manifest last. An interruption is detected by the consumer's
        # hash checks; it must never accept partially refreshed sources as sealed.
        (temporary / "manifest.json").replace(destination / "manifest.json")
    return manifest


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    for entry in snapshot(root, root / "value_cases/sources/internal"):
        print(entry["file"], entry["sha256"][:12], entry["copied_from"])


if __name__ == "__main__":
    main()
