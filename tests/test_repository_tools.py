"""Input-integrity checks that need no external datasets."""
import importlib.util
import io
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
