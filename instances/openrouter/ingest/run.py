"""Normalize the OpenRouter usage datasets, archived price lists and the Economic Index API task sample.

Reads data/raw/ (written by ingest/audit/fetch.py) and writes data/normalized/:

  model_weekly.parquet      week, model, tokens, market_tokens, share        (daily totals summed over complete weeks)
  category_weekly.parquet   week, category, model, tokens, share              (sampled weekly estimates)
  app_weekly.parquet        week, app_id, app_name, rank, tokens, requests    (ranks 1-200 each week)
  apps.parquet              app_id, app_name, category, subcategory, first_week, last_week, peak_tokens
  price_weekly.parquet      week, model, prompt_usd_mtok, completion_usd_mtok, blended_usd_mtok, priced_from
  models.parquet            model, provider, first_week, created, free_variant, matched_price_id
  catalog.parquet           every listed model: id, provider, created, first_listed, usage_model (permaslug when it was used)
  rank_threshold.parquet    week, tokens_rank200                              (volume of the 200th app each week)
  aei_tasks.parquet         task, onet_task_id, occupations, api_pct, prompt_index, completion_index, cost_index
  summary.json              Overview facts and charts

Nothing here is fitted. Calibration happens in the world at each prediction cutoff from data before that cutoff.
Model identifiers: the usage datasets name models by permaslug (dated, e.g. anthropic/claude-4-sonnet-20250522);
the price lists by id and, in later snapshots, canonical_slug. Free variants (":free") are priced at zero.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROMPT_SHARE = 0.94   # share of tokens that are prompt tokens: ~6K prompt vs ~400 completion per request, late 2025 (OpenRouter State of AI, sec. 4.3)
APP_CATEGORY_TO_USAGE = {"coding": "programming", "creative": "roleplay", "entertainment": "roleplay"}   # others use the whole-market mix
DATE_SUFFIX = re.compile(r"-(20\d{6}|20\d{2}-\d{2}-\d{2}|\d{4})$")


def log(msg: str) -> None:
    print(f"[openrouter ingest] {msg}", flush=True)


def monday(d: pd.Series) -> pd.Series:
    d = pd.to_datetime(d)
    return (d - pd.to_timedelta(d.dt.weekday, unit="D")).dt.normalize()


def _rows(paths: list[Path], extra=None) -> pd.DataFrame:
    out = []
    for p in paths:
        d = json.loads(p.read_text())
        df = pd.DataFrame(d.get("data", []))
        if df.empty:
            continue
        df["as_of"] = d.get("meta", {}).get("as_of")
        if extra:
            for k, v in extra(p).items():
                df[k] = v
        out.append(df)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def base_slug(s: str) -> tuple[str, bool]:
    if ":" in s:
        b, variant = s.split(":", 1)
        return b, variant == "free"
    return s, False


# ---------------------------------------------------------------- usage

def model_weekly(raw: Path) -> pd.DataFrame:
    d = _rows(sorted((raw / "rankings" / "daily").glob("*.json")))
    d["tokens"] = d.total_tokens.astype(float)
    d["date"] = pd.to_datetime(d.date)
    d = d.drop_duplicates(["date", "model_permaslug"], keep="last")
    d["week"] = monday(d.date)
    days = d.groupby("week").date.nunique()
    # The source lacks two single days (2025-06-15 and 2025-07-15); a week with six days is scaled by 7/6.
    full = days[days >= 6].index
    w = d[d.week.isin(full)].groupby(["week", "model_permaslug"], as_index=False).tokens.sum().rename(columns={"model_permaslug": "model"})
    w["days_observed"] = w.week.map(days)
    w["tokens"] = w.tokens * 7 / w.days_observed
    tot = w.groupby("week").tokens.sum().rename("market_tokens")
    w = w.join(tot, on="week")
    w["share"] = w.tokens / w.market_tokens
    return w.sort_values(["week", "tokens"], ascending=[True, False]).reset_index(drop=True)


def category_weekly(raw: Path) -> pd.DataFrame:
    def extra(p: Path) -> dict:
        return {"category": p.stem.rsplit("_", 1)[0].replace("_", "/")}
    d = _rows(sorted((raw / "rankings" / "category").glob("*.json")), extra)
    if d.empty:
        return d
    d["tokens"] = d.total_tokens.astype(float)
    d["week"] = monday(d.date)
    # Windows overlap at their edges; keep the latest retrieval of each (week, category, model).
    d = d.sort_values("as_of").drop_duplicates(["week", "category", "model_permaslug"], keep="last").rename(columns={"model_permaslug": "model"})
    d = d.groupby(["week", "category", "model"], as_index=False).tokens.sum()
    d["share"] = d.tokens / d.groupby(["week", "category"]).tokens.transform("sum")
    return d.sort_values(["category", "week", "tokens"], ascending=[True, True, False]).reset_index(drop=True)


def app_tables(raw: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    def wk(p: Path) -> dict:
        return {"week": pd.Timestamp(p.stem.split("_o")[0])}
    a = _rows(sorted((raw / "apps" / "weekly").glob("*.json")), wk)
    a["tokens"] = a.total_tokens.astype(float)
    a["requests"] = a.total_requests.astype(float)
    a = a.drop_duplicates(["week", "app_id"], keep="first")[["week", "app_id", "app_name", "rank", "tokens", "requests"]]
    thr = a[a["rank"] <= 200].groupby("week").tokens.min().rename("tokens_rank200").reset_index()
    # Classification: the category/subcategory in which an app carries the most tokens.
    cls = {}
    for kind in ("category", "subcategory"):
        def ex(p: Path, kind=kind) -> dict:
            return {kind: p.stem.rsplit("_", 2)[0]}
        c = _rows(sorted((raw / "apps" / kind).glob("*.json")), ex)
        if c.empty:
            cls[kind] = pd.Series(dtype=str)
            continue
        c["tokens"] = c.total_tokens.astype(float)
        c = c.groupby(["app_id", kind], as_index=False).tokens.sum().sort_values("tokens", ascending=False).drop_duplicates("app_id")
        cls[kind] = c.set_index("app_id")[kind]
    g = a.groupby("app_id")
    apps = pd.DataFrame({"app_name": g.app_name.last(), "first_week": g.week.min(), "last_week": g.week.max(), "peak_tokens": g.tokens.max(), "weeks_ranked": g.week.nunique()})
    apps["category"] = cls["category"].reindex(apps.index).fillna("other")
    apps["subcategory"] = cls["subcategory"].reindex(apps.index).fillna("other")
    apps = apps.reset_index()
    return a.sort_values(["week", "rank"]).reset_index(drop=True), apps, thr


# ---------------------------------------------------------------- prices

def price_snapshots(raw: Path) -> pd.DataFrame:
    rows = []
    for p in sorted((raw / "wayback" / "models").glob("*.json")):
        try:
            data = json.loads(p.read_text()).get("data", [])
        except (ValueError, AttributeError):
            continue
        snap = pd.Timestamp(datetime.strptime(p.stem[:8], "%Y%m%d"))
        for m in data:
            pr = m.get("pricing") or {}
            try:
                pp, pc = float(pr.get("prompt", "nan")), float(pr.get("completion", "nan"))
            except (TypeError, ValueError):
                continue
            if pp < 0 or pc < 0:          # router entries such as openrouter/auto carry -1
                continue
            rows.append({"snapshot": snap, "id": m.get("id"), "canonical_slug": m.get("canonical_slug") or "", "name": m.get("name", ""),
                         "created": pd.Timestamp(int(m["created"]), unit="s") if m.get("created") else pd.NaT,
                         "prompt_usd_mtok": pp * 1e6, "completion_usd_mtok": pc * 1e6})
    return pd.DataFrame(rows)


def match_models(models: list[str], snaps: pd.DataFrame) -> dict[str, str]:
    """usage permaslug -> price-list id (exact canonical slug, then id, then the slug without a date suffix)."""
    base = snaps[~snaps.id.str.contains(":", regex=False)]          # variant listings (":batch", ":free", ...) share the base slug
    by_canon = {r.canonical_slug: r.id for r in base.itertuples() if r.canonical_slug}
    ids = set(base.id)
    undated = defaultdict(set)
    for i in ids:
        undated[DATE_SUFFIX.sub("", i)].add(i)
    out = {}
    for m in models:
        b, _ = base_slug(m)
        if b in by_canon:
            out[m] = by_canon[b]
        elif b in ids:
            out[m] = b
        else:
            u = DATE_SUFFIX.sub("", b)
            if u in ids:
                out[m] = u
            elif len(undated.get(u, ())) == 1:
                out[m] = next(iter(undated[u]))
    return out


def price_weekly(mw: pd.DataFrame, cw: pd.DataFrame, snaps: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
    models = sorted(set(mw.model) | (set(cw.model) if not cw.empty else set()))
    models = [m for m in models if m != "other"]
    match = match_models(models, snaps)
    weeks = sorted(set(mw.week) | (set(cw.week) if not cw.empty else set()))
    snaps = snaps.sort_values("snapshot")
    rows = []
    for m in models:
        _, free = base_slug(m)
        pid = match.get(m)
        s = snaps[snaps.id == pid][["snapshot", "prompt_usd_mtok", "completion_usd_mtok"]].drop_duplicates("snapshot") if pid else None
        for w in weeks:
            if free:
                rows.append((w, m, 0.0, 0.0, "free variant")); continue
            if s is None or s.empty:
                rows.append((w, m, np.nan, np.nan, "unmatched")); continue
            prior = s[s.snapshot <= w + pd.Timedelta(days=6)]
            r = prior.iloc[-1] if len(prior) else s.iloc[0]
            rows.append((w, m, r.prompt_usd_mtok, r.completion_usd_mtok, "price list in force" if len(prior) else "first later price list"))
    p = pd.DataFrame(rows, columns=["week", "model", "prompt_usd_mtok", "completion_usd_mtok", "priced_from"])
    p["blended_usd_mtok"] = PROMPT_SHARE * p.prompt_usd_mtok + (1 - PROMPT_SHARE) * p.completion_usd_mtok
    return p, match


# ---------------------------------------------------------------- Economic Index (1P API)

def aei_tasks(raw: Path, onet_dir: Path) -> pd.DataFrame:
    files = sorted((raw / "aei").rglob("aei_raw_1p_api_*.csv"))
    if not files:
        return pd.DataFrame()
    d = pd.read_csv(files[-1])
    d = d[d.geo_id == "GLOBAL"]
    pct = d[(d.facet == "onet_task") & (d.variable == "onet_task_pct")][["cluster_name", "value"]].rename(columns={"value": "api_pct"})
    out = pct.set_index("cluster_name")
    for facet, col in (("onet_task::prompt_tokens", "prompt_index"), ("onet_task::completion_tokens", "completion_index"), ("onet_task::cost", "cost_index")):
        x = d[(d.facet == facet) & d.variable.str.endswith("_index")][["cluster_name", "value"]]
        x = x.assign(task=x.cluster_name.str.rsplit("::", n=1).str[0]).groupby("task").value.mean()
        out[col] = x.reindex(out.index)
    out = out.reset_index().rename(columns={"cluster_name": "task"})
    out = out[~out.task.isin(["none", "not_classified"])]
    ts = onet_dir / "Task Statements.txt"
    if ts.exists():
        t = pd.read_csv(ts, sep="\t", dtype=str, keep_default_na=False)
        t["key"] = t["Task"].str.strip().str.lower().str.rstrip(".")
        occ = t.groupby("key")["O*NET-SOC Code"].apply(lambda s: sorted(set(s))).rename("occupations")
        tid = t.groupby("key")["Task ID"].first().rename("onet_task_id")
        out["key"] = out.task.str.strip().str.lower().str.rstrip(".")
        out = out.join(occ, on="key").join(tid, on="key").drop(columns="key")
    out["source_period"] = files[-1].stem.split("1p_api_")[-1]
    return out.sort_values("api_pct", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------- summary

def build_summary(mw, cw, aw, apps, pw, models) -> dict:
    weeks = sorted(mw.week.unique())
    last = weeks[-1]
    mk = mw.groupby("week").market_tokens.first()
    top = mw[mw.week == last].nlargest(10, "tokens")
    top_apps = aw[aw.week == aw.week.max()].nsmallest(10, "rank")
    cover = mw.merge(pw[["week", "model", "blended_usd_mtok"]], on=["week", "model"], how="left")
    priced = cover[cover.model != "other"]
    pc = (priced.tokens * priced.blended_usd_mtok.notna()).sum() / priced.tokens.sum()
    return {
        "title": "AI token demand on OpenRouter", "period": f"{pd.Timestamp(weeks[0]).date()} .. {pd.Timestamp(last + pd.Timedelta(days=6)).date()}",
        "facts": [
            {"label": "Weeks of model usage", "value": len(weeks), "unit": ""},
            {"label": "Models named in the top 50 at least once", "value": int(mw[mw.model != "other"].model.nunique()), "unit": ""},
            {"label": "Apps ranked in the weekly top 200 at least once", "value": int(apps.app_id.nunique()), "unit": ""},
            {"label": "Tokens in the last full week (trillions)", "value": round(float(mk.iloc[-1]) / 1e12, 2), "unit": ""},
            {"label": "Named-model tokens with a matched list price", "value": round(100 * float(pc), 1), "unit": "%"},
        ],
        "org": {"units": sorted(apps.category.unique().tolist()), "roles": [{"id": s, "label": s, "headcount": int(n), "onet_code": ""} for s, n in apps.subcategory.value_counts().items()], "systems": []},
        "charts": [
            {"id": "market_tokens", "type": "line", "title": "Weekly tokens on OpenRouter (trillions)", "x_label": "", "y_label": "trillion tokens",
             "x": [str(pd.Timestamp(w).date()) for w in mk.index], "series": [{"name": "All models", "y": [round(v / 1e12, 3) for v in mk.values]}]},
            {"id": "top_models", "type": "hbar", "title": f"Top models, week of {pd.Timestamp(last).date()} (share of tokens, %)", "x_label": "", "y_label": "%",
             "x": top.model.tolist(), "series": [{"name": "Share", "y": [round(100 * v, 2) for v in top.share]}]},
            {"id": "top_apps", "type": "hbar", "title": f"Top apps, week of {pd.Timestamp(aw.week.max()).date()} (billion tokens)", "x_label": "", "y_label": "billion tokens",
             "x": top_apps.app_name.tolist(), "series": [{"name": "Tokens", "y": [round(v / 1e9, 1) for v in top_apps.tokens]}]},
        ],
    }


def main(ctx) -> None:
    raw, norm = ctx.data_raw, ctx.data_normalized
    norm.mkdir(parents=True, exist_ok=True)
    from orgsim import DATA_DIR
    mw = model_weekly(raw); log(f"model weeks: {mw.week.nunique()} weeks, {mw.model.nunique()} models")
    cw = category_weekly(raw); log(f"category weeks: {0 if cw.empty else cw.week.nunique()} weeks, {0 if cw.empty else cw.category.nunique()} categories")
    aw, apps, thr = app_tables(raw); log(f"app weeks: {aw.week.nunique()} weeks, {aw.app_id.nunique()} apps")
    snaps = price_snapshots(raw); log(f"price snapshots: {snaps.snapshot.nunique()} dates, {snaps.id.nunique()} model ids")
    pw, match = price_weekly(mw, cw, snaps)
    first = mw.groupby("model").week.min()
    created = snaps.groupby("id").created.min()
    models = pd.DataFrame({"model": first.index, "first_week": first.values})
    models["provider"] = models.model.str.split("/").str[0]
    models["free_variant"] = models.model.map(lambda m: base_slug(m)[1])
    models["matched_price_id"] = models.model.map(match)
    models["created"] = models.matched_price_id.map(created)
    log(f"price match: {models.matched_price_id.notna().sum()} of {len(models)} models")
    # Catalog of every listed model, including those that never reached the top 50: launch dates come from here.
    inv = {}
    for m, pid in match.items():
        if not base_slug(m)[1]:
            inv.setdefault(pid, m)
    g = snaps[~snaps.id.str.contains(":", regex=False)].groupby("id")
    catalog = pd.DataFrame({"created": g.created.min(), "first_listed": g.snapshot.min(), "name": g.name.last()}).reset_index()
    catalog["provider"] = catalog.id.str.split("/").str[0]
    catalog["usage_model"] = catalog.id.map(inv)
    catalog["launch"] = catalog.created.fillna(catalog.first_listed)
    at = aei_tasks(raw, DATA_DIR / "onet" / "db_31_0_text"); log(f"Economic Index API tasks: {len(at)}")
    for name, df in (("model_weekly", mw), ("category_weekly", cw), ("app_weekly", aw), ("apps", apps), ("rank_threshold", thr),
                     ("price_weekly", pw), ("models", models), ("catalog", catalog), ("aei_tasks", at)):
        df.to_parquet(norm / f"{name}.parquet", index=False)
    (norm / "summary.json").write_text(json.dumps(build_summary(mw, cw, aw, apps, pw, models), indent=1, default=str))
    (norm / "ingest_meta.json").write_text(json.dumps({"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "prompt_share": PROMPT_SHARE,
                                                       "app_category_to_usage": APP_CATEGORY_TO_USAGE}, indent=1))
    log("done")
