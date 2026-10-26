"""Run artifacts: runs/<instance>/<scenario>/<run_id>/{config.json, trace.parquet, summary.json, metrics.json}."""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .. import RUNS_DIR
from .trace import TRACE_COLUMNS, TraceEvent

_SCHEMA = pa.schema([
    ("tick", pa.int32()), ("sim_time", pa.timestamp("s")), ("agent_id", pa.string()), ("role", pa.string()),
    ("org_unit", pa.string()), ("case_id", pa.string()), ("activity", pa.string()), ("action_type", pa.string()),
    ("duration_h", pa.float32()), ("wait_h", pa.float32()), ("provenance", pa.string()), ("attributes", pa.string()),
])


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(2)


class RunWriter:
    def __init__(self, instance: str, scenario: str, run_id: str | None = None, config: dict[str, Any] | None = None, flush_every: int = 50_000) -> None:
        self.instance, self.scenario = instance, scenario
        self.run_id = run_id or new_run_id()
        self.dir = RUNS_DIR / instance / scenario / self.run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self._rows: list[dict[str, Any]] = []
        self._writer: pq.ParquetWriter | None = None
        self._flush_every = flush_every
        self.n_events = 0
        (self.dir / "config.json").write_text(json.dumps(config or {}, indent=2, default=str))

    def write_event(self, ev: TraceEvent) -> None:
        self._rows.append(ev.to_row())
        self.n_events += 1
        if len(self._rows) >= self._flush_every:
            self._flush()

    def _flush(self) -> None:
        if not self._rows:
            return
        df = pd.DataFrame(self._rows, columns=TRACE_COLUMNS)
        df["sim_time"] = pd.to_datetime(df["sim_time"])
        table = pa.Table.from_pandas(df, schema=_SCHEMA, preserve_index=False)
        if self._writer is None:
            self._writer = pq.ParquetWriter(self.dir / "trace.parquet", _SCHEMA, compression="zstd")
        self._writer.write_table(table)
        self._rows = []

    def write_rows(self, df: pd.DataFrame) -> None:
        """Bulk append a DataFrame with TRACE_COLUMNS (for vectorised worlds that emit many rows per tick)."""
        if df is None or len(df) == 0:
            return
        self._flush()
        df = df.reindex(columns=TRACE_COLUMNS)
        df["sim_time"] = pd.to_datetime(df["sim_time"])
        table = pa.Table.from_pandas(df, schema=_SCHEMA, preserve_index=False)
        if self._writer is None:
            self._writer = pq.ParquetWriter(self.dir / "trace.parquet", _SCHEMA, compression="zstd")
        self._writer.write_table(table)
        self.n_events += len(df)

    def write_json(self, name: str, payload: Any) -> Path:
        p = self.dir / name
        p.write_text(json.dumps(payload, indent=2, default=str))
        return p

    def close(self, summary: dict[str, Any] | None = None) -> Path:
        self._flush()
        if self._writer is not None:
            self._writer.close()
        elif not (self.dir / "trace.parquet").exists():
            pq.write_table(_SCHEMA.empty_table(), self.dir / "trace.parquet")
        if summary is not None:
            self.write_json("summary.json", summary)
        latest = self.dir.parent / "latest.json"
        latest.write_text(json.dumps({"run_id": self.run_id, "created": datetime.now(timezone.utc).isoformat()}))
        return self.dir


class RunReader:
    def __init__(self, instance: str, scenario: str, run_id: str) -> None:
        self.dir = RUNS_DIR / instance / scenario / run_id
        if not self.dir.exists():
            raise FileNotFoundError(self.dir)
        self.instance, self.scenario, self.run_id = instance, scenario, run_id

    def json(self, name: str) -> Any:
        p = self.dir / name
        return json.loads(p.read_text()) if p.exists() else None

    def trace(self, columns: list[str] | None = None, filters: list | None = None) -> pd.DataFrame:
        return pq.read_table(self.dir / "trace.parquet", columns=columns, filters=filters).to_pandas()

    def iter_trace(self, batch_size: int = 100_000) -> Iterator[pd.DataFrame]:
        pf = pq.ParquetFile(self.dir / "trace.parquet")
        for b in pf.iter_batches(batch_size=batch_size):
            yield b.to_pandas()


def list_runs(instance: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    base = RUNS_DIR / instance
    if not base.exists():
        return out
    scens = sorted((p for p in base.iterdir() if p.is_dir()), key=lambda p: (p.name != "baseline", p.name == "evaluation", p.name))
    for scen in scens:
        for run in sorted((p for p in scen.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True):
            summ = run / "summary.json"
            s = json.loads(summ.read_text()) if summ.exists() else {}
            out.append({"scenario": scen.name, "run_id": run.name, "complete": summ.exists(), "summary": s})
    return out


def latest_run(instance: str, scenario: str) -> str | None:
    p = RUNS_DIR / instance / scenario / "latest.json"
    if p.exists():
        return json.loads(p.read_text()).get("run_id")
    runs = [r for r in list_runs(instance) if r["scenario"] == scenario and r["complete"]]
    return runs[-1]["run_id"] if runs else None
