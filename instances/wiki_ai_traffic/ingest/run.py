"""Normalize the pageview downloads into one table per article, access method and day.

Every raw file is checked against manifests/sources.json before it is read. Each of the 1,000 listed articles is one
row set: its views are the sum over the title listed in December 2016 and, if the article was renamed since, the
title it redirects to today (views of a redirect are counted under the redirect's own title). Outputs
(data/normalized/, git-ignored):

  articles.parquet   article_id, title (as listed), current title, section and subsection of the Vital list
  views.parquet      date, article_id, access (desktop, mobile-web, mobile-app), views (user agent)
  aggregate.parquet  date, access, views: all of English Wikipedia (user agent)
  summary.json       Overview facts and charts
"""
from __future__ import annotations

import gzip
import hashlib
import json
import re
import urllib.parse
from datetime import datetime, timezone

import numpy as np
import pandas as pd

ACCESS = ("desktop", "mobile-web", "mobile-app")


def log(msg: str) -> None:
    print(f"[wiki_ai_traffic ingest] {msg}", flush=True)


def main(ctx) -> None:
    raw, norm = ctx.data_raw, ctx.data_normalized
    norm.mkdir(parents=True, exist_ok=True)
    man = json.loads((ctx.root / "manifests" / "sources.json").read_text())
    files = {f["path"]: f for f in man["files"]}

    def read(rel: str):
        p = raw / rel
        if hashlib.sha256(p.read_bytes()).hexdigest() != files[rel]["sha256"]:
            raise ValueError(f"hash mismatch: {p}")
        return json.loads(gzip.decompress(p.read_bytes()))

    rev_file = next(k for k in files if k.startswith("vital_level3_rev"))
    rev = read(rev_file)["query"]["pages"][0]["revisions"][0]
    text = rev["slots"]["main"]["content"]
    # sections (== ... ==) and subsections (=== ... ===) of the list, in page order
    rows, sec, sub = [], "", ""
    for line in text.splitlines():
        m2 = re.match(r"^==\s*([^=].*?)\s*==\s*$", line); m3 = re.match(r"^===\s*([^=].*?)\s*===\s*$", line)
        if m2:
            sec, sub = re.sub(r"\s*\(\d+.*?\)\s*$", "", m2.group(1)).strip(), ""
            continue
        if m3:
            sub = re.sub(r"\s*\(\d+.*?\)\s*$", "", m3.group(1)).strip()
            continue
        for t in re.findall(r"\[\[([^\]|#]+)(?:\|[^\]]*)?\]\]", line):
            t = t.strip()
            if ":" not in t and t not in {r["title"] for r in rows}:
                rows.append({"title": t, "section": sec, "subsection": sub})
    res = read("title_resolution.json.gz")
    normd, redir = {}, {}
    for blk in res:
        q = blk["response"]["query"]
        normd.update({n["from"]: n["to"] for n in q.get("normalized", [])})
        redir.update({r["from"]: r["to"] for r in q.get("redirects", [])})
    arts = pd.DataFrame(rows)
    arts["article_id"] = np.arange(len(arts))
    arts["listed_title"] = arts.title.map(lambda t: normd.get(t, t))
    arts["current_title"] = arts.listed_title.map(lambda t: redir.get(t, t))
    log(f"{len(arts)} articles; {int((arts.current_title != arts.listed_title).sum())} renamed since the list revision")
    safe = lambda t: urllib.parse.quote(t.replace(" ", "_"), safe="")  # noqa: E731
    parts = []
    for r in arts.itertuples():
        for acc in ACCESS:
            for t in {r.listed_title, r.current_title}:
                items = read(f"pageviews/{acc}/{safe(t)}.json.gz").get("items", [])
                if items:
                    parts.append(pd.DataFrame({"date": pd.to_datetime([i["timestamp"][:8] for i in items]), "article_id": r.article_id,
                                               "access": acc, "views": [i["views"] for i in items]}))
    views = pd.concat(parts).groupby(["date", "article_id", "access"], as_index=False).views.sum()
    views["access"] = views.access.astype("category")
    views.to_parquet(norm / "views.parquet", index=False)
    agg = []
    for acc in ACCESS:
        items = read(f"aggregate/{acc}.json.gz")["items"]
        agg.append(pd.DataFrame({"date": pd.to_datetime([i["timestamp"][:8] for i in items]), "access": acc, "views": [i["views"] for i in items]}))
    agg = pd.concat(agg, ignore_index=True)
    agg.to_parquet(norm / "aggregate.parquet", index=False)
    arts[["article_id", "title", "listed_title", "current_title", "section", "subsection"]].to_parquet(norm / "articles.parquet", index=False)
    log(f"views: {len(views):,} rows, {views.date.min().date()} .. {views.date.max().date()}")
    write_summary(ctx, arts, views, agg)


def write_summary(ctx, arts: pd.DataFrame, views: pd.DataFrame, agg: pd.DataFrame) -> None:
    m = views.groupby([views.date.dt.to_period("M"), "access"], observed=True).views.sum().unstack()
    ma = agg.groupby([agg.date.dt.to_period("M"), "access"]).views.sum().unstack()
    sec = arts.section.value_counts()
    summary = {
        "title": ctx.meta.get("title", ctx.id), "period": f"{views.date.min().date()} .. {views.date.max().date()}",
        "facts": [{"label": "Reference articles (Vital articles, Level 3, December 2016)", "value": int(len(arts)), "unit": ""},
                  {"label": "Their views in 2019 (user agent)", "value": int(views[views.date.dt.year == 2019].views.sum()), "unit": ""},
                  {"label": "Their share of all English Wikipedia views in 2019", "value": round(100 * views[views.date.dt.year == 2019].views.sum() / agg[agg.date.dt.year == 2019].views.sum(), 2), "unit": "%"},
                  {"label": "Topic sections", "value": int(arts.section.nunique()), "unit": ""}],
        "org": {"units": [{"id": s, "label": s} for s in sec.index], "roles": [], "systems": []},
        "charts": [
            {"id": "monthly_views", "type": "line", "title": "Monthly views of the 1,000 reference articles, by access method (millions)", "x_label": "month", "y_label": "views (millions)",
             "x": [str(p) for p in m.index], "series": [{"name": a, "y": [round(float(v) / 1e6, 2) for v in m[a].fillna(0)]} for a in m.columns], "note": "User agent only."},
            {"id": "monthly_all", "type": "line", "title": "All English Wikipedia views per month (billions)", "x_label": "month", "y_label": "views (billions)",
             "x": [str(p) for p in ma.index], "series": [{"name": a, "y": [round(float(v) / 1e9, 3) for v in ma[a].fillna(0)]} for a in ma.columns], "note": ""},
            {"id": "sections", "type": "hbar", "title": "Articles per section of the list", "x_label": "articles", "y_label": "",
             "x": list(sec.index), "series": [{"name": "Articles", "y": [int(v) for v in sec.values]}], "note": ""},
        ],
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    (ctx.data_normalized / "summary.json").write_text(json.dumps(summary, indent=1))


if __name__ == "__main__":
    from orgsim.instances import get_instance
    main(get_instance("wiki_ai_traffic"))
