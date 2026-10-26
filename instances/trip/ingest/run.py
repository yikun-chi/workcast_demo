"""Trip.com hybrid-WFH trial (Bloom, Han & Liang, Nature 2024): raw Stata deposit -> normalized tables.

Writes to instances/trip/data/normalized/:
  population.parquet        one row per employee (1,612): pretreatment covariates, arm, role/unit/team assignment
  reference_outcomes.json   every published outcome evaluate() scores against (never read by the world)
  summary.json              company-data facts and charts for the Overview page (contracts.md section 4)
  teams.parquet             synthetic team table (same_manager edges are derived from team_id at runtime)

Coding traps handled here (documented with the reproduction in manifests/reproduction.json):
  extendedtable2.control == 1 is CONTROL; figure2.role 1 = manager; figure5.role 1 = manager, 2 = non-manager;
  attrite_perc and promo_* are 0/100; extendedtable137_a and _b share row order (prior_performance link).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ARMS = {"0": "Control", "1": "Treatment"}
ENGINEER_SHARE = 743 / 1507          # table5_left_c: engineers among employees with a 2021H2 review
LIVE_FAR_CUTOFF_H = 0.75             # figure2.do: live_far = two-way commute > 90 min = one-way commute_hour > 0.75
TEAM_SIZE = 10                       # synthetic teams of ~8-12 (the deposit has no team identity)


def _rd(root: Path, rel: str) -> pd.DataFrame:
    return pd.read_stata(root / rel, convert_categoricals=False)


def _arm_means(df: pd.DataFrame, y: str, arm: str = "treat", scale: float = 1.0) -> dict:
    out = {}
    for a in (0, 1):
        s = df.loc[df[arm] == a, y].dropna()
        out[str(a)] = round(float(s.mean()) * scale, 4)
    out["n"] = {str(a): int(df.loc[df[arm] == a, y].notna().sum()) for a in (0, 1)}
    out["itt"] = round(out["1"] - out["0"], 4)
    se = {}
    for a in (0, 1):
        s = df.loc[df[arm] == a, y].dropna()
        se[str(a)] = round(float(s.std(ddof=1) / np.sqrt(len(s))) * scale, 4) if len(s) > 1 else None
    if se["0"] is not None and se["1"] is not None:
        se["itt"] = round(float(np.sqrt(se["0"] ** 2 + se["1"] ** 2)), 4)
    out["se"] = se
    return out


def build_population(a: pd.DataFrame, b: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    pop = a.copy()
    pop["prior_performance"] = b["prior_performance"].values          # shared row order (verified in manifests/reproduction.json)
    pop["prior_performance_missing"] = pop["prior_performance"].isna()
    pop["commute_imputed"] = pop["commute_hour"].isna()
    # Protected demographics must not enter behavior through imputation or teams.
    med = pop.groupby("managerial")["commute_hour"].transform("median")
    pop["commute_hour_filled"] = pop["commute_hour"].fillna(med)
    pop["live_far"] = np.where(pop["commute_hour"].isna(), np.nan, (pop["commute_hour"] > LIVE_FAR_CUTOFF_H).astype(float))
    for c in ("treat", "managerial", "female", "grad", "children_ind", "volunteer"):
        pop[c] = pop[c].astype(int)
    pop["age"] = pop["age"].astype(int)
    pop["tenure_years"] = pop["tenure_years"].astype(float)

    # --- role assignment (synthetic within ICs; managers are observed) ---
    ic = pop["managerial"] == 0
    n_eng = int(round(ENGINEER_SHARE * ic.sum()))
    score = 1.2 * pop["grad"] + rng.normal(0, 1.0, len(pop))
    order = score[ic].sort_values(ascending=False).index
    pop["role_id"] = "customer_service_rep"
    pop.loc[order[:n_eng], "role_id"] = "software_engineer"
    pop.loc[~ic, "role_id"] = "manager"
    pop["synthetic_assignment"] = True
    # org unit consistent with role; managers split in the IC proportion
    pop["org_unit"] = np.where(pop["role_id"] == "software_engineer", "it_division", "airfare_division")
    mgr_idx = pop.index[~ic]
    n_it_mgr = int(round(ENGINEER_SHARE * len(mgr_idx)))
    it_mgrs = rng.choice(mgr_idx, size=n_it_mgr, replace=False)
    pop.loc[it_mgrs, "org_unit"] = "it_division"

    # --- synthetic teams of ~TEAM_SIZE within org unit; arm-agnostic (random within unit) ---
    pop["team_id"] = ""
    for unit in ("airfare_division", "it_division"):
        for grp, label in ((ic, "team"), (~ic, "mgmt")):
            idx = pop.index[(pop["org_unit"] == unit) & grp]
            idx = rng.permutation(idx)
            n_teams = max(1, int(round(len(idx) / TEAM_SIZE)))
            for k, chunk in enumerate(np.array_split(idx, n_teams)):
                pop.loc[chunk, "team_id"] = f"{unit[:2]}-{label}-{k + 1:03d}"
    pop["person_id"] = [f"p{i + 1:04d}" for i in range(len(pop))]
    pop["seat"] = np.where(pop["managerial"] == 1, "manager", "employee")
    cols = ["person_id", "treat", "managerial", "role_id", "org_unit", "team_id", "seat", "age", "female", "tenure_years",
            "grad", "children_ind", "commute_hour", "commute_imputed", "commute_hour_filled", "live_far", "volunteer",
            "prior_performance", "prior_performance_missing", "synthetic_assignment"]
    return pop[cols]


def build_reference(root: Path) -> dict:
    f2 = _rd(root, "data/figure2.dta")
    ref: dict = {"arms": ARMS, "source": "doi:10.7910/DVN/6X4ZZL v1.1; computed by instances/trip/ingest/run.py"}
    att = {"all": _arm_means(f2, "attrite_perc"), "by": {}}
    att["by"]["managerial"] = {str(r): _arm_means(f2[f2.role == r], "attrite_perc") for r in (0, 1)}      # role 1 = manager
    att["by"]["female"] = {str(1 - m): _arm_means(f2[f2.male == m], "attrite_perc") for m in (0, 1)}      # male 1 -> female 0
    att["by"]["live_far"] = {str(v): _arm_means(f2[f2.live_far == v], "attrite_perc") for v in (0, 1)}
    att["by"]["live_far"]["missing"] = _arm_means(f2[f2.live_far.isna()], "attrite_perc")
    att["n_attriters"] = int((f2.attrite_perc == 100).sum())
    ref["attrition_pct"] = att

    e2 = _rd(root, "data/extendedtable2.dta"); e2["treat"] = (1 - e2["control"]).astype(int)   # control == 1 is control
    ref["satisfaction"] = {c: _arm_means(e2, c) for c in ("work_satisfaction", "work_life_balance", "life_satisfaction", "recommend_friends", "quit_intention")}
    ref["satisfaction"]["_scale"] = "0-10 except quit_intention (-0.375..0.375); endline survey 21 Jan 2022"

    perf, dist = {}, {}
    for per in ("2021H2", "2022H1", "2022H2", "2023H1"):
        d = _rd(root, f"data/figure3/figure3_{per}.dta"); y = f"perf_{per.lower()}"
        perf[per] = _arm_means(d, y)
        perf[per]["sd"] = {str(t): round(float(d.loc[d.treat == t, y].std(ddof=1)), 4) for t in (0, 1)}
        dist[per] = {str(t): {str(int(k)): int(v) for k, v in d.loc[d.treat == t, y].value_counts().sort_index().items()} for t in (0, 1)}
    ref["performance"] = perf; ref["performance_grade_dist"] = dist
    f4 = _rd(root, "data/figure4.dta")
    ref["promotion_pct"] = {per: _arm_means(f4, f"promo_{per.lower()}") for per in ("2021H2", "2022H1", "2022H2", "2023H1")}

    ef3 = _rd(root, "data/extendedfigure3.dta")
    piv = ef3.pivot_table(index="date", columns=["treat", "volunteer"], values="takeuprate")
    ref["takeup"] = {"dates": [d.strftime("%Y-%m-%d") for d in piv.index],
                     "series": {f"treat={int(t)},volunteer={int(v)}": [round(float(x), 4) for x in piv[(t, v)].values] for (t, v) in piv.columns},
                     "note": "group-level share of eligible WFH days (Wed/Fri) actually taken; reference dates 2021-08-09, 2021-09-13, 2022-01-21 (extendedfigure3.do)"}
    arm = {}
    for t in (0, 1):
        cols = [c for c in piv.columns if c[0] == t]
        w = {0: 1 - 0.3213, 1: 0.3213}       # volunteer share from extendedtable137_a
        arm[str(t)] = [round(float(sum(piv[c].iloc[i] * w[int(c[1])] for c in cols)), 4) for i in range(len(piv))]
    ref["takeup"]["by_arm_weighted"] = arm
    win = (piv.index >= "2021-09-13") & (piv.index < "2022-01-21")
    ref["takeup"]["window_means"] = {f"treat={int(t)},volunteer={int(v)}": round(float(piv[(t, v)][win].mean()), 4) for (t, v) in piv.columns}
    ref["takeup"]["window_means_by_arm"] = {str(t): round(float(np.mean(np.array(arm[str(t)])[win])), 4) for t in (0, 1)}

    f5 = _rd(root, "data/figure5.dta")
    ref["productivity_beliefs_pct"] = {w: {"all": round(float(f5[f5.wave == w].prod_percent.mean()), 4), "n": int((f5.wave == w).sum()),
                                           "managers": round(float(f5[(f5.wave == w) & (f5.role == 1)].prod_percent.mean()), 4),
                                           "non_managers": round(float(f5[(f5.wave == w) & (f5.role == 2)].prod_percent.mean()), 4)} for w in ("baseline", "endline")}
    t5c = _rd(root, "data/extendedtable5/table5_left_c.dta")
    ref["engineer_share_with_review"] = {"engineers": int(t5c.engineer.sum()), "n": int(len(t5c)), "share": round(float(t5c.engineer.mean()), 4)}
    return ref


def _hist(series: pd.Series, bins: list[float], labels: list[str]) -> list[int]:
    c = pd.cut(series.dropna(), bins=bins, labels=labels, include_lowest=True, right=False)
    return [int(x) for x in c.value_counts().reindex(labels).fillna(0).values]


def build_summary(pop: pd.DataFrame, ref: dict) -> dict:
    n = len(pop)
    history = yaml.safe_load((Path(__file__).resolve().parents[1] / "manifests/pre_policy.yaml").read_text())["attrition"]
    facts = [
        {"label": "Employees in the experiment", "value": n, "unit": ""},
        {"label": "Office-only / offered hybrid work (assigned by birthday)", "value": f"{int((pop.treat == 0).sum())} / {int((pop.treat == 1).sum())}", "unit": ""},
        {"label": "Managers", "value": int(pop.managerial.sum()), "unit": ""},
        {"label": "Divisions", "value": 2, "unit": "Airfare, IT"},
        {"label": "Mean one-way commute", "value": round(float(pop.commute_hour.mean()) * 60, 1), "unit": "min"},
        {"label": "Share with children", "value": round(float(pop.children_ind.mean()) * 100, 1), "unit": "%"},
        {"label": "Graduate degree", "value": round(float(pop.grad.mean()) * 100, 1), "unit": "%"},
        {"label": "Volunteered for the experiment", "value": round(float(pop.volunteer.mean()) * 100, 1), "unit": "%"},
        {"label": "Female", "value": round(float(pop.female.mean()) * 100, 1), "unit": "%"},
        {"label": "Mean age / tenure", "value": f"{pop.age.mean():.1f} y / {pop.tenure_years.mean():.1f} y", "unit": ""},
        {"label": "Observation period", "value": "2021-08-09 .. 2022-01-23", "unit": ""},
        {"label": "Commute missing (baseline non-respondents)", "value": int(pop.commute_imputed.sum()), "unit": ""},
        {"label": "Attrition in the preceding six months (division aggregate)", "value": history["value_pct"], "unit": "%"},
    ]
    roles = []
    for rid, lab, code in (("customer_service_rep", "Customer service representative", "43-4051.00"), ("software_engineer", "Software engineer", "15-1252.00"), ("manager", "Manager", "11-1021.00")):
        roles.append({"id": rid, "label": lab, "headcount": int((pop.role_id == rid).sum()), "onet_code": code})
    units = [{"id": u, "label": l, "headcount": int((pop.org_unit == u).sum())} for u, l in (("airfare_division", "Airfare division"), ("it_division", "IT division"))]
    def comp(col):
        return [int(((pop.treat == a) & (pop[col] == 1)).sum()) for a in (0, 1)]
    charts = [
        {"id": "composition_by_arm", "type": "bar", "title": "Workforce composition by group", "x_label": "", "y_label": "employees",
         "x": ["Office-only", "Offered hybrid work"],
         "series": [{"name": "Managers", "y": comp("managerial")}, {"name": "Non-managers", "y": [int(((pop.treat == a) & (pop.managerial == 0)).sum()) for a in (0, 1)]},
                    {"name": "Female", "y": comp("female")}, {"name": "With children", "y": comp("children_ind")}, {"name": "Volunteers", "y": comp("volunteer")}],
         "note": "The groups had similar employee characteristics before the policy (Extended Table 7)."},
        {"id": "commute_distribution", "type": "bar", "title": "One-way commute (hours)", "x_label": "hours", "y_label": "employees",
         "x": ["<0.25", "0.25-0.5", "0.5-0.75", "0.75-1", "1-1.5", "1.5-2+"],
         "series": [{"name": "Employees", "y": _hist(pop.commute_hour, [0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.5], ["<0.25", "0.25-0.5", "0.5-0.75", "0.75-1", "1-1.5", "1.5-2+"])}],
         "note": f"{int(pop.commute_imputed.sum())} employees did not report commute time."},
        {"id": "tenure_distribution", "type": "bar", "title": "Tenure (years)", "x_label": "years", "y_label": "employees",
         "x": ["0-2", "2-4", "4-6", "6-8", "8-10", "10-15", "15+"],
         "series": [{"name": "Employees", "y": _hist(pop.tenure_years, [0, 2, 4, 6, 8, 10, 15, 30], ["0-2", "2-4", "4-6", "6-8", "8-10", "10-15", "15+"])}], "note": ""},
        {"id": "age_distribution", "type": "bar", "title": "Age", "x_label": "years", "y_label": "employees",
         "x": ["<25", "25-29", "30-34", "35-39", "40-44", "45+"],
         "series": [{"name": "Employees", "y": _hist(pop.age, [0, 25, 30, 35, 40, 45, 70], ["<25", "25-29", "30-34", "35-39", "40-44", "45+"])}], "note": ""},
    ]
    return {"title": "Trip.com hybrid work (Airfare and IT divisions)", "period": "2021-08-09 .. 2022-01-23",
            "facts": facts, "org": {"units": units, "roles": roles, "systems": ["crm_ticketing", "code_repository", "video_conferencing", "hr_system"]},
            "charts": charts, "generated": datetime.now(timezone.utc).isoformat(),
            "notes": ["Role split within non-managers (engineer vs customer service) and team membership are synthetic assignments; the deposit has no role or team identity beyond the manager flag.",
                      "Outcomes (attrition, satisfaction, performance, promotion, take-up) are stored separately in reference_outcomes.json and read only by the evaluation."]}


def main(ctx) -> None:
    root = ctx.data_raw / "6X4ZZL"
    out = ctx.data_normalized
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(20211809)          # fixed: the synthetic assignment is part of the normalized data
    a = _rd(root, "data/extendedtable137_a.dta"); b = _rd(root, "data/extendedtable137_b.dta")
    assert len(a) == len(b) == 1612 and (a.treat.values == b.treat.values).all() and (a.volunteer.values == b.volunteer.values).all()
    pop = build_population(a, b, rng)
    pop.to_parquet(out / "population.parquet", index=False)
    teams = pop.groupby(["team_id", "org_unit"]).agg(size=("person_id", "size"), treated=("treat", "sum"), managers=("managerial", "sum")).reset_index()
    teams.to_parquet(out / "teams.parquet", index=False)
    ref = build_reference(root)
    (out / "reference_outcomes.json").write_text(json.dumps(ref, indent=1))
    summ = build_summary(pop, ref)
    (out / "summary.json").write_text(json.dumps(summ, indent=1))
    (out / "schema.json").write_text(json.dumps({
        "population.parquet": {c: str(t) for c, t in pop.dtypes.items()},
        "synthetic_columns": ["role_id (within non-managers)", "org_unit (managers)", "team_id", "commute_hour_filled", "person_id"],
        "pretreatment_columns": ["treat", "managerial", "age", "female", "tenure_years", "grad", "children_ind", "commute_hour", "volunteer", "prior_performance", "live_far"]}, indent=1))

    # --- reproduction check (manifests/reproduction.json) ---
    att = ref["attrition_pct"]["all"]; ws = ref["satisfaction"]["work_satisfaction"]
    print(f"[trip] population rows: {len(pop)} (expected 1612)")
    print(f"[trip] control/treatment: {int((pop.treat == 0).sum())}/{int((pop.treat == 1).sum())} (expected 820/792)")
    print(f"[trip] non-managers/managers: {int((pop.managerial == 0).sum())}/{int((pop.managerial == 1).sum())} (expected 1217/395)")
    print(f"[trip] attrition control vs treatment: {att['0']:.3f}% vs {att['1']:.3f}% (expected 7.195% vs 4.798%)")
    print(f"[trip] work satisfaction control vs treatment: {ws['0']:.3f} vs {ws['1']:.3f} (expected 7.835 vs 8.185), n {ws['n']['0']}/{ws['n']['1']}")
    print(f"[trip] engineers assigned: {int((pop.role_id == 'software_engineer').sum())} of {int((pop.managerial == 0).sum())} non-managers "
          f"({(pop.role_id == 'software_engineer').sum() / (pop.managerial == 0).sum():.3f}; target {ENGINEER_SHARE:.3f}); teams: {pop.team_id.nunique()}")
    print(f"[trip] wrote {out / 'population.parquet'}, reference_outcomes.json, summary.json, teams.parquet, schema.json")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from orgsim.instances import get_instance
    main(get_instance("trip"))
