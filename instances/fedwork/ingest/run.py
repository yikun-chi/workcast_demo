"""OPM Federal Workforce Data -> normalized tables and cohort twins for each cutoff.

Writes to instances/fedwork/data/normalized/:
  separations.parquet     every separation record in the pinned files: effective month, the file month it was published
                          in, agency, the twin cell attributes, separation type, deferred-resignation flag
  headcounts.parquet      employees per twin cell in each December snapshot (2018-2024)
  agencies.json           agency names and December headcounts
  twins_<cutoff>.parquet  cohort twins at each protocol cutoff, with separation rates fitted on records published by
                          the cutoff (calibration/selection.json fixes the specification)
  summary.json            facts and charts for the Overview page

A twin cell is agency x age band x length-of-service band x permanent appointment x full-time x supervisor.
Separation types: quit (SC), retirement (SD, SE, SG and any other retirement code), termination (SH, SJ),
transfer to another agency (SA, SB), other (everything else). Adverse-action codes are withheld by OPM.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

SEP_COLS = ["personnel_action_effective_date_yyyymm", "agency_code", "agency", "age_bracket", "length_of_service_years", "tenure_code",
            "work_schedule_code", "supervisory_status_code", "separation_category_code", "separation_category", "drp_indicator", "count"]
EMP_COLS = ["agency_code", "agency", "age_bracket", "length_of_service_years", "tenure_code", "work_schedule_code", "supervisory_status_code", "count"]
CELL = ["agency_code", "age_bracket", "los_band", "perm", "fulltime", "supervisor"]
TYPES = ["quit", "retire", "term", "transfer", "other"]
LOS_EDGES = [0, 1, 3, 5, 10, 20, 30, 200]
LOS_LABELS = ["<1", "1-3", "3-5", "5-10", "10-20", "20-30", "30+"]
AGENCY_MIN = 1000             # agencies with fewer employees at the cutoff are scored together as "Other agencies"
SEASON_K = 200                # separations at which an agency's own month-of-year pattern gets half the weight


def sep_type(code: pd.Series) -> pd.Series:
    c = code.astype(str)
    out = pd.Series("other", index=code.index)
    out[c == "SC"] = "quit"
    out[c.isin(["SD", "SE", "SG"]) | c.str.startswith("SD")] = "retire"
    out[c.isin(["SH", "SJ"])] = "term"
    out[c.isin(["SA", "SB"])] = "transfer"
    return out


def add_cell(df: pd.DataFrame) -> pd.DataFrame:
    los = pd.to_numeric(df["length_of_service_years"], errors="coerce")
    df = df.assign(los_band=pd.cut(los, LOS_EDGES, labels=LOS_LABELS, right=False).astype(str).replace("nan", "unknown"),
                   perm=df["tenure_code"].astype(str).isin(["1", "2"]).astype(int),
                   fulltime=(df["work_schedule_code"].astype(str) == "F").astype(int),
                   supervisor=(~df["supervisory_status_code"].astype(str).isin(["8", "*"])).astype(int))
    df["age_bracket"] = df["age_bracket"].astype(str)
    df["agency_code"] = df["agency_code"].astype(str)
    return df


# ----------------------------------------------------------------------------- download and verify

def fetch(ctx) -> list[dict]:
    man = json.loads((ctx.root / "manifests" / "sources.json").read_text())
    raw = ctx.data_raw / "opm"
    raw.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=300, follow_redirects=True) as c:
        for f in man["files"]:
            target = raw / f"{f['filename']}.parquet"
            if not target.exists():
                tmp = target.with_suffix(".part")
                with c.stream("GET", f["url"]) as r:
                    r.raise_for_status()
                    with tmp.open("wb") as out:
                        for chunk in r.iter_bytes():
                            out.write(chunk)
                if hashlib.sha256(tmp.read_bytes()).hexdigest() != f["sha256"]:
                    tmp.unlink()
                    raise RuntimeError(f"{f['filename']}: SHA-256 does not match the manifest; nothing was written")
                tmp.rename(target)
            if hashlib.sha256(target.read_bytes()).hexdigest() != f["sha256"]:
                raise RuntimeError(f"{target}: SHA-256 does not match the manifest")
    return man["files"]


# ----------------------------------------------------------------------------- normalized tables

def build_separations(raw: Path, files: list[dict]) -> pd.DataFrame:
    parts = []
    for f in files:
        if f["dataset"] != "separations":
            continue
        d = pd.read_parquet(raw / f"{f['filename']}.parquet", columns=SEP_COLS)
        d["file_month"] = f"{f['year']:04d}-{f['month']:02d}"
        parts.append(d)
    s = pd.concat(parts, ignore_index=True)
    ym = s["personnel_action_effective_date_yyyymm"].astype(str)
    s["effective_month"] = ym.str[:4] + "-" + ym.str[4:6]
    s["n"] = pd.to_numeric(s["count"], errors="coerce").fillna(1).astype(int)
    s["type"] = sep_type(s["separation_category_code"])
    s["drp"] = (s["drp_indicator"].astype(str) == "Y").astype(int)
    s = add_cell(s)
    return s[["effective_month", "file_month", *CELL, "agency", "type", "separation_category_code", "drp", "n"]]


def build_headcounts(raw: Path, files: list[dict]) -> pd.DataFrame:
    parts = []
    for f in files:
        if f["dataset"] != "employment":
            continue
        d = add_cell(pd.read_parquet(raw / f"{f['filename']}.parquet", columns=EMP_COLS))
        d["n"] = pd.to_numeric(d["count"], errors="coerce").fillna(1).astype(int)
        g = d.groupby(CELL, observed=True).n.sum().rename("headcount").reset_index()
        g["snapshot"] = f"{f['year']:04d}-{f['month']:02d}"
        parts.append(g)
    return pd.concat(parts, ignore_index=True)


# ----------------------------------------------------------------------------- twins at a cutoff (records published by the cutoff only)

def months_back(cutoff: str, k: int) -> list[str]:
    p = pd.Period(cutoff, "M")
    return [str(p - i) for i in range(k - 1, -1, -1)]


def visible(seps: pd.DataFrame, cutoff: str) -> pd.DataFrame:
    """Separation records an analyst could see at the end of `cutoff`: effective and published by then."""
    return seps[(seps.effective_month <= cutoff) & (seps.file_month <= cutoff)]


def agency_groups(heads: pd.DataFrame, cutoff: str) -> dict[str, str]:
    size = heads[heads.snapshot == cutoff].groupby("agency_code").headcount.sum()
    return {a: (a if n >= AGENCY_MIN else "OTHER") for a, n in size.items()}


def build_twins(seps: pd.DataFrame, heads: pd.DataFrame, cutoff: str, spec: dict) -> pd.DataFrame:
    """Cohort twins at `cutoff` with monthly separation rates by type, from records visible at the cutoff."""
    W = int(spec["window_months"]); a = float(spec["shrink"])
    months = months_back(cutoff, W)
    s = visible(seps, cutoff)
    s = s[s.effective_month.isin(months)]
    year = int(cutoff[:4])
    snaps = [f"{y}-12" for y in range(year - W // 12, year + 1)]
    h = heads[heads.snapshot.isin(snaps)].groupby(CELL, observed=True).headcount.sum() / len(snaps)
    expo = (h * W).rename("exposure")
    cnt = s.groupby([*CELL, "type"], observed=True).n.sum().unstack("type").reindex(columns=TYPES).fillna(0.0)
    tab = pd.concat([expo, cnt], axis=1).fillna(0.0)
    demo = [c for c in CELL if c != "agency_code"]
    out = heads[heads.snapshot == cutoff].set_index(CELL)[["headcount"]].copy()
    out = out.join(tab, how="left").fillna(0.0)
    for t in TYPES:
        dem = tab.groupby(level=demo)[[t, "exposure"]].sum()
        dem_rate = (dem[t] / dem["exposure"].where(dem["exposure"] > 0)).fillna(0.0)
        tab_rate = dem_rate.reindex(tab.index.droplevel("agency_code")).to_numpy()
        expected = pd.Series(tab["exposure"].to_numpy() * tab_rate, index=tab.index).groupby(level="agency_code").sum()
        observed = tab[t].groupby(level="agency_code").sum()
        factor = (observed / expected.where(expected > 0)).fillna(1.0)
        parent = dem_rate.reindex(out.index.droplevel("agency_code")).fillna(0.0).to_numpy() * factor.reindex(out.index.get_level_values("agency_code")).fillna(1.0).to_numpy()
        num = out[t].to_numpy() + a * parent
        den = out["exposure"].to_numpy() + a
        out[f"rate_{t}"] = np.where(den > 0, num / np.where(den > 0, den, 1.0), parent)
    out = out.reset_index()
    # month-of-year pattern by type: none, government-wide over the rate window, or each agency's own pattern over the
    # last 36 months shrunk toward the government-wide one (weight n / (n + SEASON_K) for an agency-type with n separations)
    s_m = s.assign(moy=s.effective_month.str[5:7].astype(int)).groupby(["type", "moy"]).n.sum().unstack("moy").reindex(index=TYPES, columns=range(1, 13)).fillna(0.0)
    gov = {t: (s_m.loc[t].to_numpy() / s_m.loc[t].to_numpy().mean()) if s_m.loc[t].to_numpy().mean() > 0 else np.ones(12) for t in TYPES}
    mode = spec.get("season", "none")
    if mode == "agency":
        s36 = visible(seps, cutoff)
        s36 = s36[s36.effective_month.isin(months_back(cutoff, 36))].assign(moy=lambda d: d.effective_month.str[5:7].astype(int))
        prof = s36.groupby(["agency_code", "type", "moy"]).n.sum().unstack("moy").reindex(columns=range(1, 13)).fillna(0.0)
    for t in TYPES:
        if mode == "none":
            f = np.ones((len(out), 12))
        elif mode == "government":
            f = np.tile(gov[t], (len(out), 1))
        else:
            f = np.tile(gov[t], (len(out), 1))
            for ag, idx in out.groupby("agency_code").groups.items():
                if (ag, t) in prof.index:
                    row = prof.loc[(ag, t)].to_numpy(); n = row.sum()
                    if n > 0:
                        wgt = n / (n + SEASON_K)
                        f[np.asarray(idx)] = wgt * row / row.mean() + (1 - wgt) * gov[t]
        for m in range(12):
            out[f"season_{t}_m{m + 1:02d}"] = np.clip(f[:, m], 0.2, 5.0)
    groups = agency_groups(heads, cutoff)
    out["agency_group"] = out.agency_code.map(groups).fillna("OTHER")
    out["person_id"] = [f"cell{i:06d}" for i in range(len(out))]
    out["role_id"] = "federal_employee"
    out["org_unit"] = out.agency_group
    out["team_id"] = ""
    out["seat"] = "employee"
    out["voluntary_rate"] = out.rate_quit + out.rate_retire
    return out.drop(columns=["exposure", *TYPES])


def actuals(seps: pd.DataFrame, heads: pd.DataFrame, cutoff: str, months: list[str]) -> pd.DataFrame:
    """Recorded separations per agency group, month and type in `months` (scoring only; any publication date)."""
    groups = agency_groups(heads, cutoff)
    s = seps[seps.effective_month.isin(months)].assign(agency_group=lambda d: d.agency_code.map(groups).fillna("OTHER"))
    return s.groupby(["agency_group", "effective_month", "type"]).n.sum().rename("n").reset_index()


def build_summary(seps: pd.DataFrame, heads: pd.DataFrame, agencies: dict) -> dict:
    pre = seps[(seps.effective_month >= "2019-01") & (seps.effective_month <= "2024-12")]
    by_m = pre.groupby("effective_month").n.sum()
    by_t = pre[pre.effective_month >= "2024-01"].groupby("type").n.sum()
    total = int(heads[heads.snapshot == "2024-12"].headcount.sum())
    facts = [{"label": "Federal employees in OPM's data, December 2024", "value": total, "unit": ""},
             {"label": "Agencies scored separately (1,000 or more employees)", "value": sum(1 for a, n in agencies["headcount_2024_12"].items() if n >= AGENCY_MIN), "unit": ""},
             {"label": "Separations in 2024", "value": int(pre[pre.effective_month >= "2024-01"].n.sum()), "unit": ""},
             {"label": "Cohort twins in December 2024", "value": int(len(heads[heads.snapshot == "2024-12"])), "unit": ""}]
    charts = [{"id": "monthly_separations", "type": "line", "title": "Separations from federal agencies per month, 2019-2024 (actual data)", "x_label": "month", "y_label": "separations",
               "x": list(by_m.index), "series": [{"name": "Actual data", "y": [int(v) for v in by_m.values]}], "note": "Effective month of the personnel action."},
              {"id": "separations_by_type", "type": "bar", "title": "Separations in 2024 by type (actual data)", "x_label": "", "y_label": "separations",
               "x": [t for t in TYPES], "series": [{"name": "Actual data", "y": [int(by_t.get(t, 0)) for t in TYPES]}], "note": ""}]
    top = sorted(agencies["headcount_2024_12"].items(), key=lambda kv: -kv[1])
    roles = [{"id": "federal_employee", "label": "Federal civilian employee", "headcount": total, "onet_code": "13-1071.00"}]
    units = [{"id": a, "label": agencies["names"].get(a, a), "headcount": n} for a, n in top if n >= AGENCY_MIN]
    return {"title": "U.S. federal civilian workforce (OPM Federal Workforce Data)", "period": "2019-01 .. 2025-12", "facts": facts,
            "org": {"units": units, "roles": roles, "systems": ["ehri"]}, "charts": charts, "generated": datetime.now(timezone.utc).isoformat(),
            "notes": ["Separations after the cutoff are read only by the evaluation."]}


def main(ctx) -> None:
    files = fetch(ctx)
    raw = ctx.data_raw / "opm"
    out = ctx.data_normalized
    out.mkdir(parents=True, exist_ok=True)
    seps = build_separations(raw, files)
    seps.to_parquet(out / "separations.parquet", index=False)
    heads = build_headcounts(raw, files)
    heads.to_parquet(out / "headcounts.parquet", index=False)
    names = seps.groupby("agency_code").agency.agg(lambda s: s.mode().iat[0]).to_dict()
    agencies = {"names": names, **{f"headcount_{s.replace('-', '_')}": heads[heads.snapshot == s].groupby("agency_code").headcount.sum().astype(int).to_dict() for s in sorted(heads.snapshot.unique())}}
    (out / "agencies.json").write_text(json.dumps(agencies, indent=1))
    sel = ctx.calibration_dir / "selection.json"
    proto = ctx.yaml("evaluation/protocol.yaml")
    if sel.exists():
        spec = json.loads(sel.read_text())["selected"]
        for c in proto.get("cutoffs") or []:
            build_twins(seps, heads, c["cutoff"], spec).to_parquet(out / f"twins_{c['cutoff']}.parquet", index=False)
    else:
        print("[fedwork] calibration/selection.json missing: run ingest/audit/select_spec.py, then ingest again to write the twins")
    (out / "summary.json").write_text(json.dumps(build_summary(seps, heads, agencies), indent=1))
    print(f"[fedwork] {len(seps):,} separation records, {heads.snapshot.nunique()} snapshots, {int(heads[heads.snapshot == '2024-12'].headcount.sum()):,} employees in 2024-12")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from orgsim.instances import get_instance
    main(get_instance("fedwork"))
