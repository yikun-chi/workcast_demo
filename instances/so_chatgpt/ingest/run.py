"""Normalize weekly Stack Overflow question counts (Stack Exchange API, written by ingest/audit/fetch.py).

Writes data/normalized/:

  series.parquet   group, period, date, value, se   (one row per Monday-to-Sunday week: questions created that week that
                   still exist; period 0 is the first week fetched)
  groups.parquet   group, label, modelled, scored
  summary.json     Overview facts and charts

ChatGPT was released on Wednesday 30 November 2022; the week of Monday 28 November 2022 is the change week. Nothing is
fitted here.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

LAUNCH_WEEK = pd.Timestamp("2022-11-28")


def log(msg: str) -> None:
    print(f"[so_chatgpt ingest] {msg}", flush=True)


def main(ctx) -> None:
    files = sorted((ctx.data_raw / "weekly").glob("*.json"))
    if not files:
        raise FileNotFoundError(f"{ctx.data_raw}/weekly missing; run instances/so_chatgpt/ingest/audit/fetch.py")
    rows = [{"date": pd.Timestamp(p.stem), "value": float(json.loads(p.read_text())["total"])} for p in files]
    s = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    full = pd.date_range(s.date.min(), s.date.max(), freq="7D")
    if len(full) != len(s):
        missing = sorted(set(full) - set(s.date))
        raise ValueError(f"weeks missing from the raw files: {[str(m.date()) for m in missing[:10]]}")
    s["period"] = np.arange(len(s))
    s["group"] = "stackoverflow"
    s["se"] = np.nan
    s = s[["group", "period", "date", "value", "se"]]
    groups = pd.DataFrame({"group": ["stackoverflow"], "label": ["Stack Overflow"], "modelled": [True], "scored": [True]})
    out = ctx.data_normalized
    out.mkdir(parents=True, exist_ok=True)
    s.to_parquet(out / "series.parquet", index=False)
    groups.to_parquet(out / "groups.parquet", index=False)
    launch = int(s.loc[s.date == LAUNCH_WEEK, "period"].iloc[0])
    pre = s[(s.period < launch) & (s.period >= launch - 52)].value.mean()
    post = s[(s.period >= launch + 52) & (s.period < launch + 104)].value.mean()
    last = s.tail(13).value.mean()
    summary = {
        "title": "Weekly questions on Stack Overflow before and after ChatGPT",
        "period": f"{s.date.min().date()} .. {(s.date.max() + pd.Timedelta(days=6)).date()}",
        "facts": [{"label": "Weeks", "value": int(len(s)), "unit": ""},
                  {"label": "Change week (ChatGPT released 30 Nov 2022)", "value": str(LAUNCH_WEEK.date()), "unit": ""},
                  {"label": "Questions per week, the year before the launch", "value": round(float(pre)), "unit": ""},
                  {"label": "Questions per week, the second year after the launch", "value": round(float(post)), "unit": ""},
                  {"label": "Questions per week, last 13 weeks", "value": round(float(last)), "unit": ""}],
        "org": {"units": [{"id": "stackoverflow", "label": "Stack Overflow"}], "roles": [{"id": "asker", "label": "Developer with a programming question", "headcount": None, "onet_code": "15-1252.00"}], "systems": []},
        "charts": [{"id": "weekly", "type": "line", "title": "New Stack Overflow questions per week", "x": [str(d.date()) for d in s.date], "x_label": "", "y_label": "questions",
                    "series": [{"name": "Actual outcome", "y": [float(v) for v in s.value], "source": "actual"}],
                    "note": "Questions that still exist (the API omits deleted questions). ChatGPT was released on 30 November 2022."}],
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    log(f"{len(s)} weeks {s.date.min().date()} .. {s.date.max().date()}; launch week = period {launch}")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from orgsim.instances import get_instance
    main(get_instance("so_chatgpt"))
