"""Local value-case snapshots must preserve integrity and require explicit refresh."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def snapshot_module():
    spec = importlib.util.spec_from_file_location("value_case_snapshot", ROOT / "value_cases/snapshot_internal.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_missing_input_preserves_existing_sealed_sources(tmp_path):
    module = snapshot_module()
    target = tmp_path / "sealed"
    target.mkdir()
    (target / "manifest.json").write_text('[]')
    (target / "openrouter_evaluation.json").write_text('old result')
    with pytest.raises(FileNotFoundError, match="Build the local evaluations"):
        module.snapshot(tmp_path, target)
    assert (target / "manifest.json").read_text() == '[]'
    assert (target / "openrouter_evaluation.json").read_text() == 'old result'


def test_local_snapshot_hashes_content_and_records_portable_paths(tmp_path, monkeypatch):
    module = snapshot_module()
    for source in module.SOURCES.values():
        path = tmp_path / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout="abc123\n"))
    destination = tmp_path / "snapshots"
    manifest = module.snapshot(tmp_path, destination)
    assert json.loads((destination / "manifest.json").read_text()) == manifest
    for entry in manifest:
        data = (destination / entry["file"]).read_bytes()
        assert entry["sha256"] == hashlib.sha256(data).hexdigest()
        assert entry["bytes"] == len(data)
        assert entry["copied_from"] == module.SOURCES[entry["file"]]
        assert entry["last_commit_of_original"] == (None if entry["copied_from"].startswith("runs/") else "abc123")


def test_default_rebuild_needs_only_sealed_inputs_and_leaves_sources_unchanged(tmp_path):
    # A small artifact fixture, not a second application checkout. No runs/ or
    # remote machines are available; accidental refresh would fail this test.
    work = tmp_path / "value_cases"
    shutil.copytree(ROOT / "value_cases", work, ignore=shutil.ignore_patterns("__pycache__"))
    (tmp_path / ".venv").symlink_to(Path(sys.prefix), target_is_directory=True)
    before = {str(p.relative_to(work)): hashlib.sha256(p.read_bytes()).hexdigest() for p in (work / "sources").rglob("*") if p.is_file()}
    result = subprocess.run(["bash", str(work / "run_all.sh")], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    after = {str(p.relative_to(work)): hashlib.sha256(p.read_bytes()).hexdigest() for p in (work / "sources").rglob("*") if p.is_file()}
    assert after == before
    for name in ("value_cases_client.md", "one_pager.md", "PROVENANCE.md"):
        assert (work / "out" / name).read_bytes() == (ROOT / "value_cases/out" / name).read_bytes()
