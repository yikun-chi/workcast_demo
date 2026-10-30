"""Ctrip work-from-home experiment (Bloom, Liang, Roberts & Ying, QJE 2015): authors' replication files -> normalized tables.

Writes to instances/ctrip/data/normalized/:
  panel.parquet             weekly performance panel of every employee in the deposit (2010 week 1 .. 2011 week 33)
  population.parquet        one row per experiment participant (249): pre-experiment covariates, arm, and
                            performance features computed from weeks before the experiment only
  reference_outcomes.json   the outcomes the evaluation scores against (never read by the world)
  summary.json              facts and charts for the Overview page
and the pre-experiment calibration to instances/ctrip/calibration/fit.json.

Weeks follow the deposit's Stata convention: week 1 starts on 1 January, week 52 takes the last days of the year.
The experiment began on Monday 6 December 2010, inside week 201049; that week is a transition week and is not
scored (as in the paper's Table 2). Scored weeks are 201050 .. 201133 (the experiment ended on 15 August 2011).
"""
from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

T0_WEEK = 201049              # first experiment week (transition week, not scored)
FIRST_SCORED = 201050
LAST_SCORED = 201133
CALLS_MIN = 20                # the paper's filter for weekly calls (phonecallraw > 20)
ARMS = {"0": "Office (control)", "1": "Home (treatment)"}


# ----------------------------------------------------------------------------- download and verify

def fetch(ctx) -> Path:
    """Download the authors' public copy once, verify its SHA-256 against manifests/sources.json, unpack the Stata files."""
    man = json.loads((ctx.root / "manifests" / "sources.json").read_text())
    src = man["files"][0]
    raw = ctx.data_raw
    raw.mkdir(parents=True, exist_ok=True)
    target = raw / src["name"]
    if not target.exists():
        tmp = target.with_suffix(".part")
        with httpx.Client(follow_redirects=True, timeout=120) as c:
            r = c.get(src["url"]); r.raise_for_status()
            tmp.write_bytes(r.content)
        if hashlib.sha256(tmp.read_bytes()).hexdigest() != src["sha256"]:
            tmp.unlink()
            raise RuntimeError(f"{src['name']}: SHA-256 does not match the manifest; nothing was written")
        tmp.rename(target)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    if digest != src["sha256"]:
        raise RuntimeError(f"{target}: SHA-256 {digest} does not match the manifest {src['sha256']}")
    out = raw / "WFH"
    if not (out / "performance_during_exper.dta").exists():
        with zipfile.ZipFile(target) as z:
            for name in z.namelist():
                if name.startswith("WFH/") and not name.endswith("/") and "__MACOSX" not in name:
                    (raw / name).parent.mkdir(parents=True, exist_ok=True)
                    (raw / name).write_bytes(z.read(name))
    return out


def _rd(root: Path, name: str) -> pd.DataFrame:
    return pd.read_stata(root / name, convert_categoricals=False)


# ----------------------------------------------------------------------------- normalized panel and population

def build_panel(root: Path) -> pd.DataFrame:
    p = _rd(root, "performance_during_exper.dta")
    tc = _rd(root, "tc_comparison.dta")[["personid", "type"]]
    p = p.merge(tc, on="personid", how="left")
    out = pd.DataFrame({
        "person_id": "c" + p.personid.astype(int).astype(str),
        "group": p.expgroup.astype(int),               # 0 office (control), 1 home (treatment), 2 Nantong site, 3 not in the experiment
        "year_week": p.year_week.astype(int),
        "perform1": p.perform1.astype(float),
        "calls": p.phonecallraw.astype(float),
        "log_calls": p.logphonecall.astype(float),
        "log_call_per_sec": p.logcallpersec.astype(float),
        "days_worked": np.exp(p.logdaysworked.astype(float)),
        "type": p["type"],
    })
    # the paper's call sample: order takers' weeks with more than 20 calls and a recorded call time
    out["calls_valid"] = out.calls.gt(CALLS_MIN) & out.log_call_per_sec.notna() & out.log_calls.notna()
    return out.sort_values(["person_id", "year_week"]).reset_index(drop=True)


def level(values: pd.Series, weeks: pd.Series, spec: dict, prior_mean: float, prior_var_between: float, var_within: float) -> float:
    """One person's level from weeks before the cutoff, by the estimator chosen on the pre-experiment holdout."""
    v = values.to_numpy(dtype=float); w = weeks.to_numpy()
    ok = np.isfinite(v)
    v, w = v[ok], w[ok]
    if not len(v):
        return float(prior_mean)
    kind = spec["estimator"]
    if kind == "last_k":
        v = v[np.argsort(w)][-int(spec["k"]):]
        return float(v.mean())
    if kind == "shrink":
        n = len(v)
        b = prior_var_between / (prior_var_between + var_within / n) if prior_var_between > 0 else 0.0
        return float(prior_mean + b * (v.mean() - prior_mean))
    return float(v.mean())


def variance_components(df: pd.DataFrame, col: str) -> tuple[float, float, float]:
    """Mean, between-person variance and within-person variance of a weekly measure (one-way random effects, moments)."""
    d = df[["person_id", col]].dropna()
    g = d.groupby("person_id")[col]
    means, ns = g.mean(), g.size()
    within = float(((d[col] - g.transform("mean")) ** 2).sum() / max(1, len(d) - len(means)))
    between = max(0.0, float(means.var(ddof=1) - within * float((1.0 / ns).mean())))
    return float(means.mean()), between, within


def pre_features(panel: pd.DataFrame, t0_week: int, spec: dict, ids: list[str]) -> pd.DataFrame:
    """Per-person performance features from weeks strictly before `t0_week` only."""
    pre = panel[(panel.year_week < t0_week) & panel.person_id.isin(ids)]
    cal = pre[pre.calls_valid]
    pm, pb, pw = variance_components(pre, "perform1")
    cm, cb, cw = variance_components(cal, "log_calls")
    rows = []
    for pid in ids:
        a = pre[pre.person_id == pid]; c = cal[cal.person_id == pid]
        rows.append({"person_id": pid,
                     "perf_level": level(a.perform1, a.year_week, spec, pm, pb, pw),
                     "calls_level": level(c.log_calls, c.year_week, spec, cm, cb, cw) if len(c) else np.nan,
                     "pre_weeks": int(a.perform1.notna().sum()), "pre_call_weeks": int(len(c)),
                     "pre_days_worked": float(a.days_worked.mean()) if a.days_worked.notna().any() else np.nan})
    return pd.DataFrame(rows)


def build_population(root: Path, panel: pd.DataFrame, spec: dict) -> pd.DataFrame:
    tc = _rd(root, "tc_comparison.dta")
    sv = _rd(root, "summary_volunteer.dta")[["personid", "commute"]]
    pop = tc.merge(sv, on="personid", how="left")
    pop["person_id"] = "c" + pop.personid.astype(int).astype(str)
    out = pd.DataFrame({
        "person_id": pop.person_id, "treat": pop.expgroup.astype(int),
        "type": pop["type"].astype(int), "order_taker": (pop["type"] == 1).astype(int),
        "role_id": np.where(pop["type"] == 1, "order_taker", "other_agent"), "org_unit": "shanghai_call_centre", "team_id": "", "seat": "employee",
        "age": pop.age.astype(float), "tenure_years": pop.tenure.astype(float) / 12.0, "prior_experience_years": pop.prior_experience.astype(float) / 12.0,
        "married": pop.married.astype(int), "children_ind": pop.children.astype(int), "age_youngest_child": pop.ageyoungestchild.astype(float),
        "rental": pop.rental.astype(int), "bedroom": pop.bedroom.astype(int), "internet": pop.internet.astype(int),
        "commute_min": pop.commute.astype(float), "commute_cost_yuan": pop.costofcommute.astype(float),
        "base_wage": pop.basewage.astype(float), "bonus": pop.bonus.astype(float), "gross_wage": pop.grosswage.astype(float),
        "tertiary": ((pop.tertiary_technical + pop.university) > 0).astype(int),
        "female": (1 - pop.men).astype(int),          # display only: never enters behaviour (CLAUDE.md rule 4)
    })
    feats = pre_features(panel, T0_WEEK, spec, out.person_id.tolist())
    return out.merge(feats, on="person_id", how="left")


# ----------------------------------------------------------------------------- pre-experiment calibration

EXIT_GAP = 4                  # an exit is a last appearance followed by at least four weeks of absence inside the window


def exit_hazard(panel: pd.DataFrame, t0_week: int, min_spell: int, start_week: int = 201001, end_week: int | None = None) -> dict:
    """Weekly exit hazard among staff outside the experiment, from weeks before `t0_week` only.

    An employee exits in week w when w is the last week they appear and the window still has `EXIT_GAP` later weeks;
    person-weeks count as at risk up to that point. Only person-weeks after at least `min_spell` observed weeks count
    (the experiment required six months of tenure).
    """
    end_week = end_week or t0_week
    d = panel[(panel.group.isin([2, 3])) & (panel.year_week >= start_week) & (panel.year_week < end_week)]
    last_wk = int(d.year_week.max())
    horizon = last_wk - EXIT_GAP                 # last week in which an exit can be seen
    g = d.groupby("person_id").year_week
    first, last = g.min(), g.max()
    at_risk, exits = 0, 0
    for pid in first.index:
        f, l = int(first[pid]), int(last[pid])
        at_risk += max(0, min(l, horizon) - (f + min_spell) + 1)
        if l <= horizon and (l - f + 1) > min_spell:
            exits += 1
    h = exits / at_risk if at_risk else float("nan")
    return {"weekly": h, "exits": exits, "person_weeks": at_risk, "min_spell_weeks": min_spell, "exit_gap_weeks": EXIT_GAP,
            "weeks": [int(d.year_week.min()), last_wk]}


def fit_calibration(panel: pd.DataFrame, pop: pd.DataFrame, t0_week: int, spec: dict) -> dict:
    """Everything the simulation takes from data, computed from weeks before `t0_week` only."""
    pre = panel[panel.year_week < t0_week]
    exp_pre = pre[pre.person_id.isin(pop.person_id)]
    # population seasonality: 2010 weekly means of all employees, relative to the weeks that set each person's level
    season = {}
    for col, valid in (("perform1", pre.perform1.notna()), ("log_calls", pre.calls_valid)):
        wk = pre[valid].groupby("year_week")[col].mean()
        if spec["estimator"] == "last_k":
            ref_weeks = sorted(wk.index)[-int(spec["k"]):]
        else:
            ref_weeks = sorted(wk.index)
        base = float(wk.loc[ref_weeks].mean())
        # 2011 week w borrows 2010 week w; December 2010 weeks after the cutoff have no earlier observation and get 0
        season[col] = {str(2011 * 100 + int(w % 100)): round(float(v - base), 5) for w, v in wk.items() if 2011 * 100 + int(w % 100) <= LAST_SCORED}
    pm, pb, pw = variance_components(exp_pre, "perform1")
    cm, cb, cw = variance_components(exp_pre[exp_pre.calls_valid], "log_calls")
    haz = exit_hazard(panel, t0_week, int(spec["min_spell"]))
    return {"t0_week": t0_week, "spec": spec, "season": season,
            "perform1": {"mean": pm, "sd_between": float(np.sqrt(pb)), "sd_within": float(np.sqrt(pw)), "sd_person_week": float(exp_pre.perform1.std())},
            "log_calls": {"mean": cm, "sd_between": float(np.sqrt(cb)), "sd_within": float(np.sqrt(cw)), "sd_person_week": float(exp_pre[exp_pre.calls_valid].log_calls.std())},
            "exit_hazard": haz,
            "weeks_scored": [FIRST_SCORED, LAST_SCORED],
            "generated_from": "instances/ctrip/ingest/run.py: weeks before the experiment only"}


# ----------------------------------------------------------------------------- reference outcomes (scoring only)

def _person_change(panel: pd.DataFrame, col: str, valid: pd.Series) -> pd.DataFrame:
    d = panel[valid & panel.group.isin([0, 1])]
    pre = d[d.year_week < T0_WEEK].groupby("person_id").agg(pre=(col, "mean"), group=("group", "first"))
    post = d[(d.year_week >= FIRST_SCORED) & (d.year_week <= LAST_SCORED)].groupby("person_id")[col].mean().rename("post")
    return pre.join(post, how="inner")


def _did(panel: pd.DataFrame, col: str, valid: pd.Series) -> dict:
    """Arm means before and after (person-week averages) and the difference in differences with a person-level SE."""
    d = panel[valid & panel.group.isin([0, 1])]
    out: dict = {"pre": {}, "post": {}, "n_persons": {}, "n_person_weeks_post": {}}
    for a in (0, 1):
        da = d[d.group == a]
        out["pre"][str(a)] = round(float(da[da.year_week < T0_WEEK][col].mean()), 5)
        post = da[(da.year_week >= FIRST_SCORED) & (da.year_week <= LAST_SCORED)]
        out["post"][str(a)] = round(float(post[col].mean()), 5)
        out["n_persons"][str(a)] = int(post.person_id.nunique()); out["n_person_weeks_post"][str(a)] = int(len(post))
    out["did"] = round((out["post"]["1"] - out["pre"]["1"]) - (out["post"]["0"] - out["pre"]["0"]), 5)
    ch = _person_change(panel, col, valid)
    ch["diff"] = ch.post - ch.pre
    g = ch.groupby("group")["diff"]
    out["se_did"] = round(float(np.sqrt((g.var(ddof=1) / g.size()).sum())), 5)
    return out


def build_reference(root: Path, panel: pd.DataFrame) -> dict:
    q = _rd(root, "quit_data.dta")
    att = {}
    for a in (0, 1):
        s = q[q.expgroup == a].quitjob
        att[str(a)] = round(float(s.mean()) * 100, 4)
    att["n"] = {str(a): int((q.expgroup == a).sum()) for a in (0, 1)}
    att["itt"] = round(att["1"] - att["0"], 4)
    se = {str(a): float(np.sqrt(q[q.expgroup == a].quitjob.mean() * (1 - q[q.expgroup == a].quitjob.mean()) / (q.expgroup == a).sum())) * 100 for a in (0, 1)}
    att["se"] = {"0": round(se["0"], 4), "1": round(se["1"], 4), "itt": round(float(np.sqrt(se["0"] ** 2 + se["1"] ** 2)), 4)}
    w = _rd(root, "attrition.dta")
    cum = {"weeks": sorted(int(x) for x in w.week.dropna().unique())}
    for a in (0, 1):
        wa = w[w.expgroup == a]
        n = wa.personid.nunique()
        first_quit = wa[wa.quitjob == 1].groupby("personid").week.min()
        cum[str(a)] = [round(100.0 * float((first_quit <= k).sum()) / n, 3) for k in cum["weeks"]]
    perf = _did(panel, "perform1", panel.perform1.notna())
    calls = _did(panel, "log_calls", panel.calls_valid)
    calls_raw = _did(panel, "calls", panel.calls_valid)
    weekly = {}
    for col, valid in (("perform1", panel.perform1.notna()), ("log_calls", panel.calls_valid), ("calls", panel.calls_valid)):
        d = panel[valid & panel.group.isin([0, 1])]
        piv = d.groupby(["year_week", "group"])[col].mean().unstack()
        weekly[col] = {"keys": [int(k) for k in piv.index], **{str(a): [round(float(x), 4) for x in piv[a]] for a in (0, 1)}}
    return {"arms": ARMS, "source": "Bloom, Liang, Roberts & Ying (2015) replication files (authors' copy; Harvard Dataverse doi:10.7910/DVN/PZQOB1); computed by instances/ctrip/ingest/run.py",
            "attrition_pct": {"all": att}, "cumulative_attrition_pct": cum,
            "measures": {"perform1": perf, "log_calls": calls, "calls": calls_raw}, "weekly": weekly,
            "weeks_scored": [FIRST_SCORED, LAST_SCORED]}


def build_summary(pop: pd.DataFrame, panel: pd.DataFrame) -> dict:
    pre = panel[(panel.year_week < T0_WEEK) & panel.group.isin([0, 1])]
    facts = [
        {"label": "Employees in the experiment", "value": len(pop), "unit": ""},
        {"label": "Office / home (assigned by birthday, even or odd)", "value": f"{int((pop.treat == 0).sum())} / {int((pop.treat == 1).sum())}", "unit": ""},
        {"label": "Order takers (calls recorded weekly)", "value": int(pop.order_taker.sum()), "unit": ""},
        {"label": "Mean age / tenure", "value": f"{pop.age.mean():.1f} y / {pop.tenure_years.mean():.1f} y", "unit": ""},
        {"label": "Mean daily commute (round trip)", "value": round(float(pop.commute_min.mean()), 1), "unit": "min"},
        {"label": "Married / with children", "value": f"{100 * pop.married.mean():.0f}% / {100 * pop.children_ind.mean():.0f}%", "unit": ""},
        {"label": "Weekly calls per order taker in 2010", "value": round(float(pre[pre.calls_valid].calls.mean()), 1), "unit": "calls"},
        {"label": "Weeks observed before the experiment", "value": int(pre.year_week.nunique()), "unit": "weeks"},
        {"label": "Staff outside the experiment in the 2010 panel", "value": int(panel[(panel.year_week < T0_WEEK) & panel.group.isin([2, 3])].person_id.nunique()), "unit": ""},
    ]
    wk = pre.groupby("year_week").agg(perf=("perform1", "mean"))
    calls = pre[pre.calls_valid].groupby("year_week").calls.mean()
    charts = [
        {"id": "pre_calls", "type": "line", "title": "Weekly calls per order taker before the experiment (2010)", "x_label": "week", "y_label": "calls",
         "x": [str(k) for k in calls.index], "series": [{"name": "Actual data", "y": [round(float(v), 1) for v in calls.values]}], "note": "Weeks with more than 20 calls."},
        {"id": "pre_performance", "type": "line", "title": "Overall performance score before the experiment (2010)", "x_label": "week", "y_label": "z-score",
         "x": [str(k) for k in wk.index], "series": [{"name": "Actual data", "y": [round(float(v), 3) for v in wk.perf.values]}], "note": ""},
    ]
    roles = [{"id": "order_taker", "label": "Order taker (phone sales)", "headcount": int(pop.order_taker.sum()), "onet_code": "43-4181.00"},
             {"id": "other_agent", "label": "Other call-centre role", "headcount": int((1 - pop.order_taker).sum()), "onet_code": "43-4051.00"}]
    return {"title": "Ctrip call centre, Shanghai (airfare and hotel booking)", "period": "2010-01-01 .. 2011-08-19",
            "facts": facts, "org": {"units": [{"id": "shanghai_call_centre", "label": "Shanghai call centre", "headcount": len(pop)}], "roles": roles, "systems": ["phone_booking"]},
            "charts": charts, "generated": datetime.now(timezone.utc).isoformat(),
            "notes": ["Outcomes after the experiment began are stored in reference_outcomes.json and read only by the evaluation."]}


def main(ctx) -> None:
    root = fetch(ctx)
    out = ctx.data_normalized
    out.mkdir(parents=True, exist_ok=True)
    sel_path = ctx.calibration_dir / "selection.json"
    if not sel_path.exists():
        raise RuntimeError("calibration/selection.json is missing: run instances/ctrip/ingest/audit/select_spec.py first")
    spec = json.loads(sel_path.read_text())["selected"]
    panel = build_panel(root)
    panel.to_parquet(out / "panel.parquet", index=False)
    pop = build_population(root, panel, spec)
    pop.to_parquet(out / "population.parquet", index=False)
    fit = fit_calibration(panel, pop, T0_WEEK, spec)
    (ctx.calibration_dir / "fit.json").write_text(json.dumps(fit, indent=1))
    ref = build_reference(root, panel)
    (out / "reference_outcomes.json").write_text(json.dumps(ref, indent=1))
    (out / "summary.json").write_text(json.dumps(build_summary(pop, panel), indent=1))
    print(f"[ctrip] population {len(pop)} ({int((pop.treat == 0).sum())} office / {int((pop.treat == 1).sum())} home); "
          f"panel {len(panel)} person-weeks; exit hazard {fit['exit_hazard']['weekly']:.5f}/week")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from orgsim.instances import get_instance
    main(get_instance("ctrip"))
