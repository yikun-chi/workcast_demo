"""Descriptive audit of the normalized complaints (design input; prints only, fits nothing)."""
from pathlib import Path

import numpy as np
import pandas as pd

norm = Path(__file__).resolve().parents[2] / "data" / "normalized"
df = pd.read_parquet(norm / "requests.parquet")
df["week"] = df.created.dt.to_period("W-SUN").dt.start_time
print("rows", len(df), "span", df.created.min(), df.created.max())
yr = df.groupby(df.created.dt.year).agg(n=("org", "size"), on_time=("on_time", "mean"), missing_on_time=("on_time", lambda s: s.isna().mean()))
print(yr)
w = df.groupby("week").size()
print("weekly total last 20 weeks\n", w.tail(20))
print("weekly by year mean", w.groupby(w.index.year).mean().round(0).to_dict())
for y0 in ["2020-01-01", "2022-01-01", "2024-01-01", "2025-09-01"]:
    sub = df[(df.created >= y0) & (df.created < pd.Timestamp(y0) + pd.Timedelta(days=364))]
    vc = sub.org.value_counts()
    print(f"\n{y0}: total {len(sub):,}; top 10 share {vc.head(10).sum()/len(sub):.3f}; companies with >=10/wk: {(vc >= 520).sum()}; >=2/wk {(vc>=104).sum()}")
    print((vc.head(15) / 52).round(1).to_string())
print("\non-time by company (2024+), top 30 by volume")
s = df[df.created >= "2024-01-01"]
g = s.groupby("org", observed=True).agg(n=("on_time", "size"), ot=("on_time", "mean")).sort_values("n", ascending=False).head(30)
print(g.to_string())
print("\nresponse values (2025+)", df[df.created >= "2025-01-01"].response.value_counts().head(8).to_dict())
print("channels", df.channel.value_counts().head(8).to_dict())
top = s.org.value_counts().head(40).index
p = df[df.org.isin(top) & (df.created >= "2021-01-01")].groupby(["org", "week"], observed=True).size().unstack(0).fillna(0)
r = np.log1p(p).diff().std()
print("\nweekly log-diff std, top 40:", r.describe().round(3).to_dict())
svb = df[df.org.astype(str).str.contains("SVB|SILICON VALLEY|Signature|FIRST REPUBLIC", case=False, regex=True)]
print("\nSVB/Signature/First Republic complaints by month:\n", svb.groupby([svb.org.astype(str), svb.created.dt.to_period("M")]).size().loc[lambda x: x > 0].tail(40).to_string())
