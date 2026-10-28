"""Normalize the BTS on-time files into flight, carrier-airport-day and airport-day tables.

Every raw file is checked against manifests/sources.json before it is read. Outputs (data/normalized/, git-ignored):

  flights/<YYYY_MM>.parquet   one row per scheduled flight: date, carrier, origin, dest, scheduled hours, cancelled
                              (with BTS cancellation code A carrier, B weather, C national air system, D security),
                              diverted, departure and arrival delay, and the delay-cause minutes
  cell_day.parquet            per date x carrier x origin group (the airports in AIRPORTS, everything else OTHER):
                              scheduled departures, cancellations by code, diverted, on-time arrivals and departures,
                              flights with weather + air-system delay of 15 minutes or more, late-aircraft delays
  arr_day.parquet             per date x carrier x destination group: scheduled arrivals (the carrier's destinations)
  airport_day.parquet         per date x airport group: flights touching the airport (departures + arrivals) and how
                              many of them were hit by weather or the air traffic system (cancellation code B or C,
                              or weather + air-system delay of 15 minutes or more)
  summary.json                Overview facts and charts

Definitions (BTS conventions): a flight arrives on time if it operated, was not diverted and arrived less than 15
minutes after its scheduled time; cancelled and diverted flights count as not on time, so on-time share is a share of
scheduled flights. AIRPORTS is fixed from 2019 traffic, before every evaluation cutoff.
"""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# The 30 airports with the most scheduled departures in calendar 2019 (computed by ingest/audit/top_airports.py
# from the 2019 files; fixed so that no later traffic chooses the airport set).
AIRPORTS = ["ATL", "ORD", "DFW", "DEN", "CLT", "LAX", "IAH", "PHX", "LGA", "SFO", "LAS", "DTW", "MSP", "BOS", "MCO",
            "SEA", "DCA", "EWR", "JFK", "PHL", "SLC", "BWI", "FLL", "SAN", "MIA", "MDW", "BNA", "TPA", "DAL", "IAD"]
COLS = {"FlightDate": "date", "Reporting_Airline": "carrier", "Tail_Number": "tail", "Flight_Number_Reporting_Airline": "flight",
        "Origin": "origin", "Dest": "dest", "CRSDepTime": "crs_dep", "CRSArrTime": "crs_arr", "DepDelay": "dep_delay",
        "ArrDelay": "arr_delay", "Cancelled": "cancelled", "CancellationCode": "cancel_code", "Diverted": "diverted",
        "CarrierDelay": "carrier_delay", "WeatherDelay": "weather_delay", "NASDelay": "nas_delay",
        "SecurityDelay": "security_delay", "LateAircraftDelay": "late_aircraft_delay", "Distance": "distance"}


def log(msg: str) -> None:
    print(f"[airline_ops ingest] {msg}", flush=True)


def sha256(p: Path) -> str:
    with p.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def read_month(path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(path) as z:
        csvs = [n for n in z.namelist() if n.lower().endswith(".csv") and "/" not in n and ".." not in n]
        if len(csvs) != 1:
            raise ValueError(f"{path.name}: expected one CSV member, found {csvs}")
        with z.open(csvs[0]) as f:
            df = pd.read_csv(io.TextIOWrapper(f, encoding="latin1"), usecols=list(COLS), dtype={"CancellationCode": "string", "Tail_Number": "string"},
                             low_memory=False)
    df = df.rename(columns=COLS)
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df["cancelled"] = df["cancelled"].fillna(0).astype(bool)
    df["diverted"] = df["diverted"].fillna(0).astype(bool)
    for c in ("crs_dep", "crs_arr", "flight"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(-1).astype("int32")
    for c in ("dep_delay", "arr_delay", "carrier_delay", "weather_delay", "nas_delay", "security_delay", "late_aircraft_delay", "distance"):
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("float32")
    df["cancel_code"] = df["cancel_code"].fillna("").astype(str)
    for c in ("carrier", "origin", "dest", "tail"):
        df[c] = df[c].fillna("").astype(str)
    return df


def flags(df: pd.DataFrame) -> pd.DataFrame:
    operated = ~df.cancelled & ~df.diverted
    out = pd.DataFrame({
        "sched": 1,
        "canc_A": df.cancelled & df.cancel_code.eq("A"), "canc_B": df.cancelled & df.cancel_code.eq("B"),
        "canc_C": df.cancelled & df.cancel_code.eq("C"), "canc_D": df.cancelled & df.cancel_code.eq("D"),
        "cancelled": df.cancelled, "diverted": df.diverted,
        "arr_ontime": operated & (df.arr_delay < 15), "dep_ontime": ~df.cancelled & (df.dep_delay < 15),
        "wxnas15": (df.weather_delay.fillna(0) + df.nas_delay.fillna(0)) >= 15,
        "late_ac15": df.late_aircraft_delay.fillna(0) >= 15,
    }, index=df.index).astype("int32")
    out["exo"] = (df.cancelled & df.cancel_code.isin(["B", "C"])) | (out.wxnas15 > 0)
    out["exo"] = out["exo"].astype("int32")
    return out


def group(code: pd.Series) -> pd.Series:
    return code.where(code.isin(AIRPORTS), "OTHER")


def main(ctx) -> None:
    raw, norm = ctx.data_raw, ctx.data_normalized
    man = json.loads((ctx.root / "manifests" / "sources.json").read_text())
    audit = json.loads((ctx.root / "ingest" / "audit" / "top_airports_2019.json").read_text())
    if sorted(a["airport"] for a in audit["airports"]) != sorted(AIRPORTS):
        raise ValueError("AIRPORTS differs from ingest/audit/top_airports_2019.json; rerun the audit script and update the list")
    (norm / "flights").mkdir(parents=True, exist_ok=True)
    cells, arrs, aps = [], [], []
    n_flights = 0
    for f in man["files"]:
        p = raw / f["name"]
        out = norm / "flights" / (f["name"].replace("ontime_", "").replace(".zip", ".parquet"))
        if not p.exists():
            raise FileNotFoundError(f"{p} missing: run instances/airline_ops/ingest/download.py")
        if out.exists() and out.stat().st_mtime > p.stat().st_mtime:
            df = pd.read_parquet(out)
        else:
            if sha256(p) != f["sha256"]:
                raise ValueError(f"hash mismatch: {p}")
            df = read_month(p)
            df.to_parquet(out, index=False)
        n_flights += len(df)
        fl = flags(df)
        k = pd.DataFrame({"date": df.date, "carrier": df.carrier, "airport": group(df.origin)})
        cells.append(pd.concat([k, fl], axis=1).groupby(["date", "carrier", "airport"], observed=True).sum().reset_index())
        arrs.append(pd.DataFrame({"date": df.date, "carrier": df.carrier, "airport": group(df.dest), "sched_arr": 1})
                    .groupby(["date", "carrier", "airport"]).sum().reset_index())
        both = pd.concat([pd.DataFrame({"date": df.date, "airport": group(df.origin), "n": 1, "exo": fl.exo}),
                          pd.DataFrame({"date": df.date, "airport": group(df.dest), "n": 1, "exo": fl.exo})])
        aps.append(both.groupby(["date", "airport"]).sum().reset_index())
        log(f"{f['name']}: {len(df):,} flights")
    cell = pd.concat(cells, ignore_index=True)
    arr = pd.concat(arrs, ignore_index=True)
    ap = pd.concat(aps, ignore_index=True)
    cell.to_parquet(norm / "cell_day.parquet", index=False)
    arr.to_parquet(norm / "arr_day.parquet", index=False)
    ap.to_parquet(norm / "airport_day.parquet", index=False)
    log(f"{n_flights:,} flights; {cell.date.min().date()} .. {cell.date.max().date()}; {cell.carrier.nunique()} carriers")
    write_summary(ctx, cell, ap, n_flights)


def write_summary(ctx, cell: pd.DataFrame, ap: pd.DataFrame, n_flights: int) -> None:
    cd = cell.groupby(["date", "carrier"])[["sched", "cancelled", "arr_ontime"]].sum().reset_index()
    month = cd.assign(m=cd.date.dt.to_period("M")).groupby("m")[["sched", "cancelled", "arr_ontime"]].sum()
    by_c = cd.groupby("carrier")[["sched", "cancelled", "arr_ontime"]].sum().sort_values("sched", ascending=False)
    summary = {
        "title": ctx.meta.get("title", ctx.id), "period": f"{cell.date.min().date()} .. {cell.date.max().date()}",
        "facts": [
            {"label": "Scheduled flights", "value": int(n_flights), "unit": ""},
            {"label": "Reporting carriers", "value": int(cell.carrier.nunique()), "unit": ""},
            {"label": "Airports modelled individually", "value": len(AIRPORTS), "unit": ""},
            {"label": "Flights arriving on time (share of scheduled)", "value": round(100 * by_c.arr_ontime.sum() / by_c.sched.sum(), 1), "unit": "%"},
            {"label": "Flights cancelled", "value": round(100 * by_c.cancelled.sum() / by_c.sched.sum(), 2), "unit": "%"},
        ],
        "org": {"units": [{"id": c, "label": c} for c in by_c.index], "roles": [], "systems": []},
        "charts": [
            {"id": "monthly_flights", "type": "bar", "title": "Scheduled flights per month", "x_label": "month", "y_label": "flights",
             "x": [str(p) for p in month.index], "series": [{"name": "Scheduled flights", "y": [int(v) for v in month.sched]}], "note": ""},
            {"id": "monthly_ontime", "type": "line", "title": "Share of scheduled flights arriving on time, by month", "x_label": "month", "y_label": "%",
             "x": [str(p) for p in month.index], "series": [{"name": "On time", "y": [round(100 * a / s, 2) for a, s in zip(month.arr_ontime, month.sched)]}], "note": "Cancelled and diverted flights count as not on time."},
            {"id": "carrier_volume", "type": "hbar", "title": "Scheduled flights by carrier", "x_label": "flights", "y_label": "",
             "x": list(by_c.index), "series": [{"name": "Flights", "y": [int(v) for v in by_c.sched]}], "note": ""},
        ],
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    (ctx.data_normalized / "summary.json").write_text(json.dumps(summary, indent=1))


if __name__ == "__main__":
    from orgsim.instances import get_instance
    main(get_instance("airline_ops"))
