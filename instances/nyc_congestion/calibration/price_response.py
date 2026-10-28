"""Riders' price response, measured on the state congestion surcharge of 2 February 2019.

From 12:01 a.m. on Saturday 2 February 2019 (NYS Tax notice N-19-2) every yellow taxi trip that began in, ended in or
passed through Manhattan south of 96th Street paid $2.50 more (tax.ny.gov congestion surcharge page). Trips touching that
zone are the treated group; yellow taxi trips touching neither end of it are the control. The change in the treated
group's trips relative to the control's, from the weeks before to the weeks after, net of the same calendar change a
year earlier (2018, weeks aligned by weekday), is the surcharge's effect on trips. Divided by the change in log price
(the treated trips' average rider price before tips in the weeks before, plus $2.50), it is the price elasticity of
trips. Windows of 2 to 6 weeks either side give the range; 4 weeks is the central value.

Only January-March 2018 and 2019 enter, years before every prediction cutoff. Writes calibration/price_response.json.

    python instances/nyc_congestion/calibration/price_response.py
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SURCHARGE = 2.50
CHANGE = {2019: pd.Timestamp("2019-02-02"), 2018: pd.Timestamp("2018-02-03")}     # the same weekday a year earlier
WINDOWS = (2, 3, 4, 5, 6)
CENTRAL = 4


def window_change(d: pd.DataFrame, t0: pd.Timestamp, weeks: int) -> dict[str, float]:
    b = d[(d.date >= t0 - pd.Timedelta(weeks=weeks)) & (d.date < t0)].groupby("group")
    a = d[(d.date >= t0) & (d.date < t0 + pd.Timedelta(weeks=weeks))].groupby("group")
    tb, ta = b.trips.sum(), a.trips.sum()
    price_before = float(b.price_sum.sum()["treated"] / b.priced_trips.sum()["treated"])
    return {"treated": math.log(ta["treated"] / tb["treated"]), "control": math.log(ta["control"] / tb["control"]), "price_before": price_before}


def main() -> None:
    d = pd.read_parquet(ROOT / "data" / "normalized" / "surcharge2019_daily.parquet")
    rows = []
    for w in WINDOWS:
        c19, c18 = window_change(d, CHANGE[2019], w), window_change(d, CHANGE[2018], w)
        did = (c19["treated"] - c19["control"]) - (c18["treated"] - c18["control"])
        dlogp = math.log((c19["price_before"] + SURCHARGE) / c19["price_before"])
        rows.append({"weeks": w, "effect_log_trips": round(did, 5), "price_before_usd": round(c19["price_before"], 3), "dlog_price": round(dlogp, 5),
                     "elasticity": round(did / dlogp, 4), "treated_change_2019": round(c19["treated"], 5), "control_change_2019": round(c19["control"], 5),
                     "treated_change_2018": round(c18["treated"], 5), "control_change_2018": round(c18["control"], 5)})
    central = next(r for r in rows if r["weeks"] == CENTRAL)
    el = [r["elasticity"] for r in rows]
    out = {"elasticity": central["elasticity"], "range": [min(el), max(el)], "central_window_weeks": CENTRAL, "windows": rows,
           "source": "yellow taxi trip records, Jan-Mar 2018 and 2019 (data/normalized/surcharge2019_daily.parquet); NYS Tax notice N-19-2; tax.ny.gov congestion surcharge page",
           "applies_to": "every rider group whose trips carry the 2025 charge; the 2019 measurement is on yellow taxis and is applied to Uber and Lyft riders as well"}
    (ROOT / "calibration" / "price_response.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
