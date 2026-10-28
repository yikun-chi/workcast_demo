"""The 30 airports with the most scheduled departures in calendar 2019, the fixed airport set of the airline world.

2019 precedes every evaluation cutoff (the first is 2021-07-05), so no traffic after a cutoff chooses the airports.
Writes ingest/audit/top_airports_2019.json; ingest/run.py carries the list as AIRPORTS and checks it against this file.

  python -I instances/airline_ops/ingest/audit/top_airports.py
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    counts = pd.Series(dtype=float)
    for m in range(1, 13):
        p = ROOT / "data" / "raw" / f"ontime_2019_{m:02d}.zip"
        with zipfile.ZipFile(p) as z:
            name = [n for n in z.namelist() if n.lower().endswith(".csv")][0]
            with z.open(name) as f:
                df = pd.read_csv(io.TextIOWrapper(f, encoding="latin1"), usecols=["Origin"])
        counts = counts.add(df.Origin.value_counts(), fill_value=0)
    top = counts.sort_values(ascending=False)
    out = {"year": 2019, "rule": "most scheduled departures (cancelled flights included) in the twelve 2019 files",
           "airports": [{"airport": a, "departures": int(n)} for a, n in top.head(30).items()],
           "share_of_departures": round(float(top.head(30).sum() / top.sum()), 4), "airports_total": int(len(top))}
    (ROOT / "ingest" / "audit" / "top_airports_2019.json").write_text(json.dumps(out, indent=1) + "\n")
    print([r["airport"] for r in out["airports"]], out["share_of_departures"])


if __name__ == "__main__":
    main()
