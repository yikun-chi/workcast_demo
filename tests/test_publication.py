"""Publication must preserve snapshot integrity and never overwrite local data."""
from __future__ import annotations

import hashlib
import gzip
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
    responses = {route: {} for route in ("/", "/results", "/evaluation", "/insights", "/insights-summary", "/scenario-results", "/summary", "/scenarios", "/tables", "/ontology/concepts")}
    responses["/tables"] = []
    responses["/scenario-results"] = []
    module.write_json(source / "demo.json", {"responses": responses, "tables": {}})
    module.write_json(source / "index.json", {"schema_version": 3, "instances": [{"id": "demo", "plugins": []}], "files": {"demo.json": module.digest(source / "demo.json")}})
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


def table_fixture(tmp_path):
    import pandas as pd

    module, source = public_fixture(tmp_path)
    # More than one file and one chunk, with nulls, booleans, timestamps and Unicode.
    frame = pd.DataFrame({"person_id": ["p:1", "p:2", "p:3", "p:4", "p:5"],
                          "name": ["A", "Élise", None, "Comma, and\nnewline", "Last record"],
                          "value": [0.0, float("nan"), 2.5, -1, 4],
                          "flag": [True, False, True, False, True], "month": [1, 1, 2, 2, 2],
                          "date": pd.to_datetime(["2020-01-01"] * 5)})
    path = tmp_path / "partitioned.parquet"
    (path / "month=1").mkdir(parents=True)
    (path / "month=2").mkdir()
    frame.iloc[:2].drop(columns="month").to_parquet(path / "month=1/a.parquet", index=False)
    frame.iloc[2:].drop(columns="month").to_parquet(path / "month=2/b.parquet", index=False)
    metadata = {"name": "population.parquet", "rows": len(frame), "columns": list(frame.columns)}
    table = module.export_table(path, source, "demo", metadata, chunk_size=3)
    bundle = json.loads((source / "demo.json").read_text())
    bundle["responses"]["/tables"] = [metadata]
    bundle["tables"] = {metadata["name"]: table}
    module.write_json(source / "demo.json", bundle)
    index = json.loads((source / "index.json").read_text())
    index["files"] = {name: module.digest(source / name) for name in ["demo.json", *table["chunks"]]}
    module.write_json(source / "index.json", index)
    return module, source, table, frame


def test_public_table_roundtrip_keeps_all_rows_values_and_partition_boundaries(tmp_path):
    module, source, table, frame = table_fixture(tmp_path)
    output = tmp_path / "site"
    module.build_site(source, output)
    chunks = [json.loads(gzip.decompress((output / "public-data" / p).read_bytes())) for p in table["chunks"]]
    assert [len(c) for c in chunks] == [3, 2]
    assert [row for chunk in chunks for row in chunk] == json.loads(frame.to_json(orient="values", date_format="iso"))


def test_live_table_schema_and_stable_sort_preserve_complete_records(tmp_path, monkeypatch):
    import importlib
    from types import SimpleNamespace
    import pandas as pd

    server = importlib.import_module("orgsim.server.app")
    frame = pd.DataFrame({"person_id": ["p1", "p2", "p3"], "score": [2.5, None, 2.5], "enabled": [True, False, False]})
    frame.to_parquet(tmp_path / "population.parquet", index=False)
    monkeypatch.setattr(server, "_ctx", lambda _iid: SimpleNamespace(data_normalized=tmp_path))
    table = server.tables("demo")[0]
    assert table["rows"] == 3
    assert table["columns"] == list(frame.columns)
    assert [f["name"] for f in table["schema"]] == list(frame.columns)
    assert all(f["type"] for f in table["schema"])
    page = server.table_rows("demo", "population.parquet", offset=0, limit=50, sort="score", desc=1)
    assert [r["person_id"] for r in page["rows"]] == ["p1", "p3", "p2"]
    assert page["rows"][-1] == {"person_id": "p2", "score": None, "enabled": False}


@pytest.mark.parametrize("failure", ["corrupt", "missing", "traversal", "short_rows"])
def test_invalid_table_snapshot_leaves_previous_site_intact(tmp_path, failure):
    module, source, table, _ = table_fixture(tmp_path)
    output = tmp_path / "site"
    module.build_site(source, output)
    before = (output / "public-data/demo.json").read_bytes()
    path = source / table["chunks"][0]
    index = json.loads((source / "index.json").read_text())
    if failure == "corrupt":
        path.write_bytes(b"bad")
    elif failure == "missing":
        path.unlink()
    elif failure == "traversal":
        bundle = json.loads((source / "demo.json").read_text())
        bundle["tables"][table["name"]]["chunks"][0] = "../secrets.json.gz"
        module.write_json(source / "demo.json", bundle)
        index["files"]["demo.json"] = module.digest(source / "demo.json")
    else:
        path.write_bytes(gzip.compress(b"[]", mtime=0))
        index["files"][table["chunks"][0]] = module.digest(path)
    module.write_json(source / "index.json", index)
    with pytest.raises((ValueError, FileNotFoundError)):
        module.build_site(source, output)
    assert (output / "public-data/demo.json").read_bytes() == before


def test_public_history_identity_and_trace_integrity(tmp_path):
    import pandas as pd
    module, source = public_fixture(tmp_path)
    prefix = Path('runs/demo/baseline/run1')
    history = prefix / 'history.json.gz'
    (source / prefix).mkdir(parents=True)
    (source / history).write_bytes(gzip.compress(json.dumps({'scenario':'baseline','run_id':'run1','trace_rows':2}).encode()))
    path = tmp_path / 'trace.parquet'
    pd.DataFrame({'agent_id':['p1','p2'],'tick':[0,24]}).to_parquet(path,index=False)
    trace = module.export_table(path,source,'demo',{'name':'trace','columns':['agent_id','tick'],'rows':2},chunk_size=1,prefix=prefix/'trace')
    bundle=json.loads((source/'demo.json').read_text())
    bundle['responses']['/scenario-results']=[{'run':{'scenario':'baseline','run_id':'run1'}}]
    bundle['run_data']={'baseline/run1':{'history':history.as_posix(),'trace':trace}}
    module.write_json(source/'demo.json',bundle)
    index=json.loads((source/'index.json').read_text())
    index['files']={p.relative_to(source).as_posix():module.digest(p) for p in source.rglob('*') if p.is_file() and p.name!='index.json'}
    module.write_json(source/'index.json',index)
    module.validate_snapshot(source)
    # Corruption in an event chunk is rejected before a new site can be built.
    (source/trace['chunks'][1]).write_bytes(b'broken')
    with pytest.raises(ValueError,match='checksum'):
        module.validate_snapshot(source)


def test_public_replay_rejects_wrong_totals_and_escaping_paths(tmp_path):
    module, source = public_fixture(tmp_path)
    prefix = Path('runs/demo/baseline/run1')
    (source / prefix).mkdir(parents=True)
    history = prefix / 'history.json.gz'
    replay_path = prefix / 'replay.json.gz'
    (source/history).write_bytes(gzip.compress(json.dumps({'scenario':'baseline','run_id':'run1','trace_rows':0}).encode()))
    replay={'scenario':'baseline','run_id':'run1','agent':'','total':0,'frames':[]}
    (source/replay_path).write_bytes(gzip.compress(json.dumps(replay).encode()))
    bundle=json.loads((source/'demo.json').read_text())
    bundle['responses']['/scenario-results']=[{'run':{'scenario':'baseline','run_id':'run1'}}]
    run={'history':history.as_posix(),'replay':replay_path.as_posix(),'trace':{'name':'trace','columns':[],'total':0,'chunk_size':10000,'chunks':[]}}
    bundle['run_data']={'baseline/run1':run}
    def save():
        module.write_json(source/'demo.json',bundle)
        index=json.loads((source/'index.json').read_text())
        index['files']={p.relative_to(source).as_posix():module.digest(p) for p in source.rglob('*') if p.is_file() and p.name!='index.json'}
        module.write_json(source/'index.json',index)
    save();module.validate_snapshot(source)
    replay['role']='Manager'
    (source/replay_path).write_bytes(gzip.compress(json.dumps(replay).encode()))
    save()
    with pytest.raises(ValueError,match='Replay identity or event count'):
        module.validate_snapshot(source)
    replay.pop('role')
    replay['total']=1
    (source/replay_path).write_bytes(gzip.compress(json.dumps(replay).encode()))
    save()
    with pytest.raises(ValueError,match='Replay identity or event count'):
        module.validate_snapshot(source)
    run['replay']='../escape.json.gz';save()
    with pytest.raises(ValueError,match='Invalid replay path'):
        module.validate_snapshot(source)
