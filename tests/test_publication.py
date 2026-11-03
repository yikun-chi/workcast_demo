"""Publication must preserve snapshot integrity and never overwrite local data."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[1]


def script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def archive_fixture(tmp_path, members):
    module = script("release_snapshot")
    archive = tmp_path / "data-demo.tar.gz"
    files = {}
    with tarfile.open(archive, "w:gz") as tar:
        for name, value in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(value)
            tar.addfile(info, io.BytesIO(value))
            files[name] = {"bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()}
    asset = {"name": archive.name, "kind": "data", "bytes": archive.stat().st_size, "sha256": module.digest(archive), "files": files}
    (tmp_path / "snapshot.json").write_text(json.dumps({"schema_version": 1, "assets": [asset]}))
    return module, archive, asset


def test_restore_exact_files_and_idempotent_repeat(tmp_path):
    module, _, _ = archive_fixture(tmp_path, {"instances/demo/data/raw/input.csv": b"x\n1\n"})
    destination = tmp_path / "checkout"
    module.restore(tmp_path, destination)
    target = destination / "instances/demo/data/raw/input.csv"
    assert target.read_bytes() == b"x\n1\n"
    before = target.stat().st_mtime_ns
    module.restore(tmp_path, destination)
    assert target.stat().st_mtime_ns == before


def test_restore_conflict_preflights_all_files(tmp_path):
    module, _, _ = archive_fixture(tmp_path, {"instances/demo/data/a.csv": b"new", "instances/demo/data/z.csv": b"snapshot"})
    destination = tmp_path / "checkout"
    existing = destination / "instances/demo/data/z.csv"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"local work")
    with pytest.raises(ValueError, match="Existing file differs"):
        module.restore(tmp_path, destination)
    assert existing.read_bytes() == b"local work"
    assert not (existing.parent / "a.csv").exists()


@pytest.mark.parametrize("path", ["../escape", "/tmp/escape", "instances/demo/data/../../secrets", "agent.md"])
def test_restore_rejects_unsafe_archive_paths(tmp_path, path):
    module, _, _ = archive_fixture(tmp_path, {path: b"bad"})
    with pytest.raises(ValueError, match="Unsafe|outside"):
        module.restore(tmp_path, tmp_path / "checkout")


def test_corrupt_archive_does_not_restore_anything(tmp_path):
    module, archive, _ = archive_fixture(tmp_path, {"instances/demo/data/input.csv": b"ok"})
    with archive.open("ab") as stream:
        stream.write(b"corruption")
    with pytest.raises(ValueError, match="checksum"):
        module.restore(tmp_path, tmp_path / "checkout")
    assert not list((tmp_path / "checkout").rglob("*.csv"))


def public_fixture(tmp_path):
    module = script("export_site")
    source = tmp_path / "public-data"
    source.mkdir()
    responses = {route: {} for route in ("/", "/results", "/evaluation", "/insights", "/summary", "/scenarios", "/tables", "/ontology/concepts")}
    module.write_json(source / "demo.json", {"responses": responses})
    module.write_json(source / "index.json", {"schema_version": 1, "instances": [{"id": "demo", "plugins": []}], "files": {"demo.json": module.digest(source / "demo.json")}})
    return module, source


def test_public_build_only_contains_allowlisted_snapshot_files(tmp_path):
    module, source = public_fixture(tmp_path)
    (source / "private.json").write_text('{"private":true}')
    output = tmp_path / "site"
    module.build_site(source, output)
    html = (output / "index.html").read_text()
    assert 'name="workcast-mode" content="static"' in html
    assert 'src="ui/app.js"' in html
    assert not (output / "public-data/private.json").exists()
    assert not (output / "ui/dev").exists()
    assert not (output / "runs").exists()
    assert not (output / "data").exists()


def test_public_build_fails_before_replacing_site_when_snapshot_changed(tmp_path):
    module, source = public_fixture(tmp_path)
    output = tmp_path / "site"
    module.build_site(source, output)
    before = (output / "public-data/demo.json").read_bytes()
    (source / "demo.json").write_text('{}')
    with pytest.raises(ValueError, match="checksum"):
        module.build_site(source, output)
    assert (output / "public-data/demo.json").read_bytes() == before
