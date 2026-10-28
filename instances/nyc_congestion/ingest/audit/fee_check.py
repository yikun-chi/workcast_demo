"""Development check, not a reported result: where and when the congestion charges appear on trip records.

Prints, for one month of yellow taxi records, the share of trips that start and end in the same taxi zone that carry the
charge (by zone) and the share of all trips carrying it by pickup hour. Used to confirm that the charge applies at all
hours and to read the zone membership the ingest derives.

    python instances/nyc_congestion/ingest/audit/fee_check.py 2025-01 cbd_congestion_fee
    python instances/nyc_congestion/ingest/audit/fee_check.py 2019-03 congestion_surcharge
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]


def main(month: str, col: str) -> None:
    f = ROOT / "data" / "raw" / "trips" / "yellow" / f"yellow_tripdata_{month}.parquet"
    d = pd.read_parquet(f, columns=["tpep_pickup_datetime", "PULocationID", "DOLocationID", col])
    z = pd.read_csv(ROOT / "data" / "raw" / "misc" / "taxi_zone_lookup.csv").set_index("LocationID")
    d["fee"] = d[col] > 0
    print(d[col].round(2).value_counts().head(8).to_string())
    s = d[d.PULocationID == d.DOLocationID].groupby("PULocationID").agg(n=("fee", "size"), share=("fee", "mean")).join(z)
    pd.set_option("display.width", 200)
    print(s[s.share > 0.02].sort_values("share").to_string())
    print("by hour:", d.groupby(d.tpep_pickup_datetime.dt.hour).fee.mean().round(3).to_dict())


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
