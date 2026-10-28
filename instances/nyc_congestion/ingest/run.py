"""Normalize the NYC TLC trip records into daily trip counts by service, zone flow and time band.

Reads data/raw/ (written by ingest/fetch.py) and writes data/normalized/:

  zones.parquet              LocationID, borough, zone, in_crz, crz_evidence, in_zone_2019, zone_2019_evidence
  trips_daily.parquet        date, service (yellow|hvfhv), flow (within|into|out_of|outside), band (day|night),
                             trips, price_sum (what riders paid before tips and the new congestion charge), priced_trips,
                             fee_trips, fee_sum (the congestion relief zone charge, recorded from 2025)
  series_daily.parquet       date, series_id, value               the demand world's input: trips per series and day
                             (missing on recording outages)
  outages.parquet            date, service, trips, reference      days a service's records are mostly missing
  series.parquet             series_id, service, flow, band, label, charged (the 2025 charge applies to the flow)
  price_daily.parquet        date, series_id, price               average rider price per trip, before tips and the new charge
  surcharge2019_daily.parquet  date, group (treated|control), trips, price_sum, priced_trips   yellow taxis, Jan-Mar 2018 and 2019
  summary.json               Overview facts and charts

Zone membership. The Congestion Relief Zone (Manhattan south of and including 60th Street) is read from the charge
itself: a zone is in it when at least 40% of yellow taxi trips that start and end inside that zone in January-March 2025
carry the charge (zones straddling 60th Street show 13-34%, zones inside 64-86%, zones outside under 8%). The 2019 state
surcharge zone (Manhattan south of 96th Street) is read the same way from February-March 2019. Only the boundary is
taken from these months; no trip count after a cutoff enters any prediction. Trips with an unknown zone (264, 265) are
dropped. A trip's flow: within (starts and ends in the zone), into (ends in it), out_of (starts in it), outside.
Time band: day 06:00-19:59 by pickup time, night otherwise.

Nothing here is fitted.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

FLOWS = ["within", "into", "out_of", "outside"]
BANDS = ["day", "night"]
SERVICES = {"yellow": "Yellow taxi", "hvfhv": "Uber and Lyft"}
FILE = {"yellow": "yellow", "hvfhv": "fhvhv"}                  # TLC file prefix per service
FLOW_LABEL = {"within": "within the zone", "into": "into the zone", "out_of": "out of the zone", "outside": "outside the zone"}
UNKNOWN_ZONES = (264, 265)
EVIDENCE_SHARE = 0.4
COLS = {"yellow": ["tpep_pickup_datetime", "PULocationID", "DOLocationID", "total_amount", "tip_amount"],
        "hvfhv": ["pickup_datetime", "PULocationID", "DOLocationID", "base_passenger_fare", "tolls", "bcf", "sales_tax", "congestion_surcharge", "airport_fee"]}


def log(msg: str) -> None:
    print(f"[nyc_congestion ingest] {msg}", flush=True)


def zone_evidence(files: list[Path], fee_col: str, start: str | None = None) -> pd.DataFrame:
    """Share of trips starting and ending in the same zone that carry the charge, per zone."""
    parts = []
    for f in files:
        d = pd.read_parquet(f, columns=["tpep_pickup_datetime", "PULocationID", "DOLocationID", fee_col])
        if start:
            d = d[d.tpep_pickup_datetime >= pd.Timestamp(start)]
        d = d[d.PULocationID == d.DOLocationID]
        parts.append(d.assign(fee=d[fee_col] > 0)[["PULocationID", "fee"]])
    d = pd.concat(parts)
    return d.groupby("PULocationID").fee.agg(["size", "mean"]).rename(columns={"size": "n", "mean": "share"})


def zones(raw: Path) -> pd.DataFrame:
    z = pd.read_csv(raw / "misc" / "taxi_zone_lookup.csv").rename(columns={"Borough": "borough", "Zone": "zone", "service_zone": "service_zone"})
    y = raw / "trips" / "yellow"
    crz = zone_evidence([y / f"yellow_tripdata_2025-0{m}.parquet" for m in (1, 2, 3)], "cbd_congestion_fee", "2025-01-05")
    z19 = zone_evidence([y / f"yellow_tripdata_2019-0{m}.parquet" for m in (2, 3)], "congestion_surcharge", "2019-02-02")
    z = z.set_index("LocationID")
    z["crz_evidence"] = crz.share.reindex(z.index)
    z["zone_2019_evidence"] = z19.share.reindex(z.index)
    man = z.borough.eq("Manhattan")
    z["in_crz"] = man & (z.crz_evidence >= EVIDENCE_SHARE) & (crz.n.reindex(z.index) >= 10)
    z["in_zone_2019"] = man & (z.zone_2019_evidence >= EVIDENCE_SHARE) & (z19.n.reindex(z.index) >= 10)
    return z.reset_index()


def rider_price(kind: str, t: dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """What the rider paid per trip before tips and before the 2025 charge, and whether the record is a priced trip."""
    if kind == "yellow":
        p = np.nan_to_num(t["total_amount"]) - np.nan_to_num(t["tip_amount"])
        if "cbd_congestion_fee" in t:
            p = p - np.nan_to_num(t["cbd_congestion_fee"])
        ok = t["total_amount"] > 0
    else:
        p = sum(np.nan_to_num(t[c]) for c in ("base_passenger_fare", "tolls", "bcf", "sales_tax", "congestion_surcharge", "airport_fee"))
        ok = t["base_passenger_fare"] > 0
    return p, ok


def aggregate_month(kind: str, f: Path, in_crz: np.ndarray) -> pd.DataFrame:
    """Per (day, flow, band): trips, price_sum, priced_trips, fee_trips, fee_sum, summed over the file in batches."""
    y, m = (int(x) for x in re.search(r"(\d{4})-(\d{2})", f.name).groups())
    lo, hi = pd.Timestamp(y, m, 1), pd.Timestamp(y, m, 1) + pd.offsets.MonthBegin(1)
    pf = pq.ParquetFile(f)
    cols = COLS[kind] + (["cbd_congestion_fee"] if "cbd_congestion_fee" in pf.schema_arrow.names else [])
    ndays = (hi - lo).days
    acc = np.zeros((ndays * len(FLOWS) * len(BANDS), 5))
    for b in pf.iter_batches(batch_size=2_000_000, columns=cols):
        t = {c: b.column(c).to_numpy(zero_copy_only=False) for c in cols}
        ts = t[cols[0]].astype("datetime64[s]")
        pu, do = t["PULocationID"].astype(int), t["DOLocationID"].astype(int)
        keep = (ts >= np.datetime64(lo)) & (ts < np.datetime64(hi)) & ~np.isin(pu, UNKNOWN_ZONES) & ~np.isin(do, UNKNOWN_ZONES) & (pu < len(in_crz)) & (do < len(in_crz))
        if kind == "yellow":
            keep &= t["total_amount"] > 0
        ts, pu, do = ts[keep], pu[keep], do[keep]
        tk = {c: v[keep] for c, v in t.items()}
        a, b_ = in_crz[pu], in_crz[do]
        flow = np.where(a & b_, 0, np.where(~a & b_, 1, np.where(a & ~b_, 2, 3)))
        hour = (ts - ts.astype("datetime64[D]")).astype(int) // 3600
        band = np.where((hour >= 6) & (hour < 20), 0, 1)
        day = (ts.astype("datetime64[D]") - np.datetime64(lo.date())).astype(int)
        key = (day * len(FLOWS) + flow) * len(BANDS) + band
        price, ok = rider_price(kind, tk)
        fee = np.nan_to_num(tk["cbd_congestion_fee"]) if "cbd_congestion_fee" in tk else np.zeros(len(key))
        n = len(acc)
        acc[:, 0] += np.bincount(key, minlength=n)
        acc[:, 1] += np.bincount(key, weights=np.where(ok, price, 0.0), minlength=n)
        acc[:, 2] += np.bincount(key, weights=ok.astype(float), minlength=n)
        acc[:, 3] += np.bincount(key, weights=(fee > 0).astype(float), minlength=n)
        acc[:, 4] += np.bincount(key, weights=fee, minlength=n)
    idx = pd.MultiIndex.from_product([pd.date_range(lo, hi - pd.Timedelta(days=1)), FLOWS, BANDS], names=["date", "flow", "band"])
    return pd.DataFrame(acc, index=idx, columns=["trips", "price_sum", "priced_trips", "fee_trips", "fee_sum"]).reset_index()


def surcharge_2019(raw: Path, in19: np.ndarray) -> pd.DataFrame:
    """Yellow taxi trips per day touching the 2019 surcharge zone (treated) or not (control), January-March 2018 and 2019."""
    out = []
    for f in sorted((raw / "trips" / "yellow").glob("yellow_tripdata_201[89]-0[123].parquet")):
        y, m = (int(x) for x in re.search(r"(\d{4})-(\d{2})", f.name).groups())
        lo, hi = pd.Timestamp(y, m, 1), pd.Timestamp(y, m, 1) + pd.offsets.MonthBegin(1)
        cols = ["tpep_pickup_datetime", "PULocationID", "DOLocationID", "total_amount", "tip_amount"]
        has_cs = "congestion_surcharge" in pq.ParquetFile(f).schema_arrow.names
        d = pd.read_parquet(f, columns=cols + (["congestion_surcharge"] if has_cs else []))
        d = d[(d.tpep_pickup_datetime >= lo) & (d.tpep_pickup_datetime < hi) & (d.total_amount > 0)
              & ~d.PULocationID.isin(UNKNOWN_ZONES) & ~d.DOLocationID.isin(UNKNOWN_ZONES)]
        treated = in19[d.PULocationID.to_numpy()] | in19[d.DOLocationID.to_numpy()]
        price = d.total_amount - d.tip_amount.fillna(0) - (d.congestion_surcharge.fillna(0) if has_cs else 0)
        g = pd.DataFrame({"date": d.tpep_pickup_datetime.dt.normalize(), "group": np.where(treated, "treated", "control"), "price": price})
        out.append(g.groupby(["date", "group"]).price.agg(["size", "sum"]).rename(columns={"size": "trips", "sum": "price_sum"}).reset_index())
    s = pd.concat(out, ignore_index=True)
    s["priced_trips"] = s.trips
    return s


def main(ctx, zones_only: bool = False) -> None:
    raw, out = ctx.data_raw, ctx.data_normalized
    out.mkdir(parents=True, exist_ok=True)
    z = zones(raw)
    z.to_parquet(out / "zones.parquet", index=False)
    in_crz = np.zeros(int(z.LocationID.max()) + 1, bool); in_crz[z.LocationID[z.in_crz]] = True
    in19 = np.zeros_like(in_crz); in19[z.LocationID[z.in_zone_2019]] = True
    log(f"zones: {int(z.in_crz.sum())} in the congestion relief zone, {int(z.in_zone_2019.sum())} in the 2019 surcharge zone")
    s19 = surcharge_2019(raw, in19)
    s19.to_parquet(out / "surcharge2019_daily.parquet", index=False)
    log(f"2019 surcharge window: {len(s19)} rows")
    if zones_only:
        return
    parts = []
    for kind in SERVICES:
        for f in sorted((raw / "trips" / FILE[kind]).glob(f"{FILE[kind]}_tripdata_*.parquet")):
            if f.name < f"{FILE[kind]}_tripdata_2022-01":
                continue
            m = aggregate_month(kind, f, in_crz)
            m["service"] = kind
            parts.append(m)
            log(f"{f.name}: {int(m.trips.sum()):,} trips")
    t = pd.concat(parts, ignore_index=True)[["date", "service", "flow", "band", "trips", "price_sum", "priced_trips", "fee_trips", "fee_sum"]]
    t = t.sort_values(["date", "service", "flow", "band"]).reset_index(drop=True)
    t.to_parquet(out / "trips_daily.parquet", index=False)
    t["series_id"] = t.service + ":" + t.flow + ":" + t.band
    out_days = recording_outages(t)
    out_days.to_parquet(out / "outages.parquet", index=False)
    bad = t.set_index(["date", "service"]).index.isin(out_days.set_index(["date", "service"]).index)
    log(f"recording outages: {len(out_days)} service-days set to missing")
    t[["date", "series_id"]].assign(value=t.trips.where(~bad)).to_parquet(out / "series_daily.parquet", index=False)
    pr = t[t.priced_trips > 0]
    pr[["date", "series_id"]].assign(price=pr.price_sum / pr.priced_trips).to_parquet(out / "price_daily.parquet", index=False)
    meta = t[["series_id", "service", "flow", "band"]].drop_duplicates().reset_index(drop=True)
    meta["label"] = meta.service.map(SERVICES) + ", " + meta.flow.map(FLOW_LABEL) + ", " + meta.band
    meta["charged"] = meta.flow != "outside"
    meta.to_parquet(out / "series.parquet", index=False)
    write_summary(out, t, z)


OUTAGE_SHARE = 0.15


def recording_outages(t: pd.DataFrame) -> pd.DataFrame:
    """Days on which a service's records are mostly missing (a recording gap, not demand): the day's trips fall below
    15% of the median of the same weekday over the four weeks before it. Storm days keep a third or more of the usual
    volume and are kept; these gaps keep 3-7%. Only earlier days enter the comparison."""
    tot = t.groupby(["service", "date"]).trips.sum()
    rows = []
    for s, x in tot.groupby(level=0):
        x = x.droplevel(0)
        ref = pd.concat([x.shift(7 * k, freq="D") for k in range(1, 5)], axis=1).reindex(x.index).median(axis=1)
        bad = x[(x < OUTAGE_SHARE * ref) & ref.notna()]
        rows += [{"date": d, "service": s, "trips": float(v), "reference": float(ref[d])} for d, v in bad.items()]
    return pd.DataFrame(rows, columns=["date", "service", "trips", "reference"])


def write_summary(out: Path, t: pd.DataFrame, z: pd.DataFrame) -> None:
    t = t.copy()
    t["week"] = t.date - pd.to_timedelta((t.date.dt.day_of_week + 1) % 7, unit="D")       # weeks start on Sunday
    full = t.groupby("week").date.nunique()
    full = full[full == 7].index
    w = t[t.week.isin(full) & t.flow.isin(["within", "into"])].groupby(["week", "service"]).trips.sum().unstack()
    change = pd.Timestamp("2025-01-05")
    before = w[(w.index < change) & (w.index >= change - pd.Timedelta(weeks=52))].mean()
    after = w[w.index >= change].mean()
    facts = [{"label": "Trips in the records (2022 onwards)", "value": int(t.trips.sum()), "unit": ""},
             {"label": "Taxi zones in the congestion relief zone", "value": int(z.in_crz.sum()), "unit": ""},
             {"label": "Weeks of data", "value": int(len(full)), "unit": ""}]
    for s, lab in SERVICES.items():
        facts.append({"label": f"{lab} trips ending in the zone, average week in the year before the charge", "value": round(float(before.get(s, 0))), "unit": ""})
    chart = {"id": "weekly_zone_trips", "type": "line", "title": "Trips ending in the congestion relief zone, by week (thousands)", "x_label": "", "y_label": "thousand trips",
             "x": [str(d.date()) for d in w.index], "series": [{"name": SERVICES[s], "y": [round(float(v) / 1e3, 1) for v in w[s]]} for s in SERVICES if s in w],
             "note": "Actual outcome from the TLC trip records. Weeks run Sunday to Saturday; the charge started on Sunday 5 January 2025."}
    summary = {"title": "NYC taxi and ride-hail trips and congestion pricing", "period": f"{t.date.min().date()} .. {t.date.max().date()}",
               "facts": facts, "org": {"units": [{"id": f"ou:{s}", "label": l} for s, l in SERVICES.items()], "roles": [], "systems": []},
               "charts": [chart], "after_mean": {s: float(after.get(s, 0)) for s in SERVICES},
               "generated": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    (out / "summary.json").write_text(json.dumps(summary, indent=1))


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from orgsim.instances import get_instance
    main(get_instance("nyc_congestion"), zones_only="--zones-only" in sys.argv)
