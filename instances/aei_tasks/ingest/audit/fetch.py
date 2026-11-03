"""Download the Anthropic Economic Index releases (Claude.ai conversations by O*NET task or SOC occupation).

Source: Hugging Face dataset Anthropic/EconomicIndex at a pinned revision (the approach of
instances/openrouter/ingest/audit/fetch.py). Licence: the data documentation says "Data released under CC-BY"; the
dataset card metadata lists MIT. Both are recorded. Each file is saved unchanged under data/raw/<release path> and never
overwritten; manifests/sources.json records URL, retrieval time, size and SHA-256.

  python instances/aei_tasks/ingest/audit/fetch.py
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
MANIFEST = ROOT / "manifests" / "sources.json"
REVISION = "4e5f69fab13a9c3f7d0dcc31a6f893a9818738f6"
BASE = f"https://huggingface.co/datasets/Anthropic/EconomicIndex/resolve/{REVISION}/"
FILES = [
    "release_2025_02_10/README.md", "release_2025_02_10/onet_task_mappings.csv", "release_2025_02_10/onet_task_statements.csv", "release_2025_02_10/SOC_Structure.csv",
    "release_2025_03_27/README.md", "release_2025_03_27/task_pct_v1.csv", "release_2025_03_27/task_pct_v2.csv",
    "release_2025_09_15/data_documentation.md", "release_2025_09_15/data/intermediate/aei_raw_claude_ai_2025-08-04_to_2025-08-11.csv",
    "release_2025_09_15/data/intermediate/onet_task_statements.csv", "release_2025_09_15/data/intermediate/soc_structure.csv",
    "release_2026_01_15/data_documentation.md", "release_2026_01_15/data/intermediate/aei_raw_claude_ai_2025-11-13_to_2025-11-20.csv",
    "release_2026_03_24/data_documentation.md", "release_2026_03_24/data/aei_raw_claude_ai_2026-02-05_to_2026-02-12.csv",
    "release_2026_06_26/data_documentation.md", "release_2026_06_26/data/aei_claude_ai_2026-06-26.csv",
]


def main() -> None:
    client = httpx.Client(timeout=900, follow_redirects=True, headers={"User-Agent": "orgsim-data/0.1"})
    for name in FILES:
        p = RAW / name
        if p.exists():
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".part")
        with client.stream("GET", BASE + name) as r:
            r.raise_for_status()
            with tmp.open("wb") as out:
                for chunk in r.iter_bytes():
                    out.write(chunk)
        tmp.replace(p)
        print(f"saved {name} ({p.stat().st_size:,} bytes)", flush=True)
    files = [{"path": (RAW / n).relative_to(ROOT).as_posix(), "url": BASE + n, "bytes": (RAW / n).stat().st_size,
              "sha256": hashlib.sha256((RAW / n).read_bytes()).hexdigest(),
              "retrieved": datetime.fromtimestamp((RAW / n).stat().st_mtime, timezone.utc).isoformat(timespec="seconds")} for n in FILES]
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps({
        "sources": [{"id": "anthropic_economic_index", "url": f"https://huggingface.co/datasets/Anthropic/EconomicIndex/tree/{REVISION}", "revision": REVISION,
                     "license": "Data CC BY (data_documentation.md, 'Data released under CC-BY'); dataset card metadata lists MIT",
                     "attribution": "Anthropic Economic Index (Anthropic), Hugging Face Anthropic/EconomicIndex"}],
        "n_files": len(files), "total_bytes": sum(x["bytes"] for x in files), "files": files}, indent=1))


if __name__ == "__main__":
    main()
