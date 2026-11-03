"""Local durable decision/checkpoint adapter, independent of planner frameworks."""
import json
from contextlib import contextmanager, closing
from pathlib import Path
import sqlite3


class SQLiteDecisionRepository:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS artifacts (kind TEXT, key TEXT, value TEXT NOT NULL, PRIMARY KEY(kind, key))")

    @contextmanager
    def _connect(self):
        with closing(sqlite3.connect(self.path, timeout=30)) as connection, connection:
            yield connection

    def read(self, kind: str, key: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute("SELECT value FROM artifacts WHERE kind=? AND key=?", (kind, key)).fetchone()
        return json.loads(row[0]) if row else None

    def write_once(self, kind: str, key: str, value: dict) -> None:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        with self._connect() as connection:
            connection.execute("INSERT OR IGNORE INTO artifacts VALUES (?, ?, ?)", (kind, key, encoded))
            saved = connection.execute("SELECT value FROM artifacts WHERE kind=? AND key=?", (kind, key)).fetchone()[0]
            if saved != encoded:
                raise ValueError(f"Conflicting {kind} for existing key {key}")
