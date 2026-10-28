"""Descriptive audit of the normalized 311 requests (design input; prints only, fits nothing)."""
from pathlib import Path

import numpy as np
import pandas as pd

norm = Path(__file__).resolve().parents[2] / "data" / "normalized"
df = pd.read_parquet(norm / "requests.parquet")
print("rows", len(df), "span", df.created.min(), df.created.max())
print("closed share by year", df.groupby(df.created.dt.year).closed.apply(lambda s: round(float(s.notna().mean()), 4)).to_dict())
print("weekly mean by year", (df.groupby(df.created.dt.year).size() / 52).round(0).to_dict())
for y0 in ["2019-01-01", "2022-01-01", "2025-09-01"]:
    sub = df[(df.created >= y0) & (df.created < pd.Timestamp(y0) + pd.Timedelta(days=364))]
    h = ((sub.closed - sub.created) / pd.Timedelta(hours=1)).fillna(np.inf)
    g = sub.assign(h=h).groupby("org", observed=True).agg(n=("h", "size"), med_h=("h", "median"), p_open=("closed", lambda s: s.isna().mean()))
    g["per_week"] = g.n / 52
    print(f"\n{y0}: total {len(sub):,}")
    print(g.sort_values("n", ascending=False).head(16).round(2).to_string())
s = df[df.created >= "2025-01-01"]
for o in ["NYPD", "HPD", "DSNY", "DOT", "DEP"]:
    vc = s[s.org == o].segment.value_counts(normalize=True).head(8).round(3)
    print(f"\n{o} top complaint types (2025+):", vc.to_dict())
wk = df.created.dt.to_period("W-SUN").dt.start_time
tot = df.groupby([wk, df.org], observed=True).size().unstack().fillna(0)
top = tot.sum().sort_values(ascending=False).head(12).index
print("\nweekly log-diff std by agency:", np.log1p(tot[top]).diff().std().round(3).to_dict())
