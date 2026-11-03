"""Input-integrity checks that need no external datasets."""
import importlib.util
import io
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_failed_download_never_publishes_an_input(tmp_path, monkeypatch):
    module = script("download_data")
    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b"corrupt download"))
    monkeypatch.setattr(module.time, "sleep", lambda *_: None)
    target = tmp_path / "source.zip"
    with pytest.raises(ValueError, match="Checksum mismatch"):
        module.fetch("https://example.org/data", target, "0" * 64)
    assert not target.exists()
    assert not list(tmp_path.iterdir())


def test_existing_corrupt_input_is_not_overwritten(tmp_path):
    module = script("download_data")
    target = tmp_path / "source.zip"
    target.write_bytes(b"local data")
    with pytest.raises(ValueError, match="Checksum mismatch"):
        module.fetch("https://example.org/data", target, "0" * 64)
    assert target.read_bytes() == b"local data"
    with pytest.raises(ValueError, match="escapes destination"):
        module.safe_path(tmp_path, "../outside")


def test_fresh_snapshot_keeps_published_hashes_and_rejects_incomplete_retrieval(tmp_path, monkeypatch):
    module = script("download_data")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    root = tmp_path / "instances/so_chatgpt"
    (root / "manifests").mkdir(parents=True)
    raw = root / "data/raw/weekly"
    raw.mkdir(parents=True)
    paths = [f"data/raw/weekly/{week}.json" for week in ("2021-03-08", "2021-03-15")]
    pinned = json.dumps({"files": [{"path": path, "sha256": "0" * 64} for path in paths]})
    (root / "manifests/sources.json").write_text(pinned)
    entries = []
    for path in paths:
        target = root / path
        target.write_text('{"total": 10}')
        entries.append({"path": path, "sha256": module.digest(target)})
    local = root / "data/sources.local.json"
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **k: local.write_text(json.dumps({"files": entries})))
    module.snapshot_instance("so_chatgpt", verify_only=False, refresh=True)
    assert (root / "manifests/sources.json").read_text() == pinned
    with pytest.raises(ValueError, match="Checksum mismatch"):
        module.snapshot_instance("so_chatgpt", verify_only=True, refresh=False)
    local.write_text(json.dumps({"files": entries[:1]}))
    with pytest.raises(RuntimeError, match="incomplete"):
        module.snapshot_instance("so_chatgpt", verify_only=True, refresh=True)


def test_openrouter_refresh_accepts_new_retrieval_dates_but_requires_history(tmp_path, monkeypatch):
    module = script("download_data")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    root = tmp_path / "instances/openrouter"
    (root / "manifests").mkdir(parents=True)
    stable = "data/raw/apps/weekly/2025-01-06_o0.json"
    old = [stable, "data/raw/probe/latest_2026-10-27.json", "data/raw/session_cost/2026-10-27/o0.json",
           "data/raw/wayback/cdx_2026-10-27.json"]
    (root / "manifests/sources.json").write_text(json.dumps({"files": [{"path": p} for p in old]}))
    files = []
    for path in (stable, *(p.replace("2026-10-27", "2026-11-03") for p in old[1:])):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('{}')
        files.append({"path": path, "sha256": module.digest(target)})
    local = root / "data/sources.local.json"
    local.write_text(json.dumps({"files": files}))
    module.snapshot_instance("openrouter", verify_only=True, refresh=True)
    local.write_text(json.dumps({"files": files[1:]}))
    with pytest.raises(RuntimeError, match="incomplete"):
        module.snapshot_instance("openrouter", verify_only=True, refresh=True)
