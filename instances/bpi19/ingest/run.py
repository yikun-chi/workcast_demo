"""Normalize BPI19 and fit process distributions on a bounded pre-policy window.

calibration/fit.yaml fixes the final training boundary. Model selection is
reproduced with --training-end 2018-07-01; the selected model is then refitted
through August 31. A fit may never cross the policy change. Only prefix events
enter transitions, state-conditioned delays, executor shares, calendars and
Aalen-Johansen competing-risk curves. Right-censored events are not completions.

Cleaning removes out-of-range dates and exact duplicates and collapses repeated
service-entry events. The all-log user table is for display only; execution
infers roles again from the prediction prefix. Full-log summaries and constraint
support are descriptive, never inputs for parameter fitting.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from orgsim.worlds.survival import aalen_johansen, week_slot

TRAIN_START, TRAIN_END = pd.Timestamp("2018-01-01"), pd.Timestamp("2018-07-01")   # [start, end)
LOG_START, LOG_END = pd.Timestamp("2018-01-01"), pd.Timestamp("2019-02-01")
END_FOLLOWUP_DAYS = 45
IPW_CAP = 2.0      # cap on the censoring weight L/(L-d); cap 2 minimizes p50/p90 error against full follow-up of train cases
Q_GRID = [0.0, 0.02, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 0.98, 0.99]
CORE_EXCEPTIONS = ["Change Quantity", "Change Price", "Cancel Invoice Receipt", "Cancel Goods Receipt", "Delete Purchase Order Item", "Remove Payment Block"]
END = "<END>"
SURV_GRID_H = [0, 1, 2, 3, 4, 6, 8, 12, 18, 24, 36, 48, 72, 96, 120, 168, 240, 336, 504, 672, 840, 1008, 1344, 1680, 2016, 2520, 3024, 3600, 4344]
SURV_MIN_N, SURV_MIN_CAUSE = 20, 10        # observations per curve; observed events per cause
CALENDAR_MIN_R2, CALENDAR_MIN_N = 0.5, 1000
STEADY_FROM = pd.Timestamp("2018-03-01")   # the shop floor is empty on 2018-01-01 and reaches steady state by March (ingest/audit/analysis.json)
SAME_USER_MIN_N = 30
MIN_STATE_N = 20
FLAG_ACTS = {"g": "Record Goods Receipt", "v": "Vendor creates invoice", "i": "Record Invoice Receipt", "r": "Remove Payment Block", "c": "Clear Invoice"}

# audited facts to verify against (ingest/audit/analysis.json)
EXPECTED = {"events_raw": 1_595_923, "cases": 251_734, "out_of_window": 327, "duplicates": 132_748, "users_human": 607, "users_batch": 20}


def log(msg: str) -> None:
    print(f"[bpi19 ingest] {msg}", flush=True)


def wquantile(x: np.ndarray, w: np.ndarray, qs: list[float]) -> list[float]:
    order = np.argsort(x)
    x, w = x[order], w[order]
    cw = np.cumsum(w) - 0.5 * w
    cw /= w.sum()
    return [float(v) for v in np.interp(qs, cw, x)]


def fit_calendar(tr: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, steady_from: pd.Timestamp) -> dict:
    """Weekly run-slot model per activity. Thresholds (x_early, x_late) are chosen once on the activity with the most
    concentrated weekly volume (highest R^2) and shared, so every activity's multipliers refer to the same calendar.
    R^2 is measured on every training week; the multipliers (slot mean / overall mean) are measured on the weeks from
    `steady_from` on, because the log starts with an empty shop floor and the run volumes ramp up until then."""
    mondays = pd.date_range(start, end - pd.Timedelta(days=1), freq="7D")
    mondays = mondays[mondays + pd.Timedelta(days=4) < end]           # weeks whose working days (Mon-Fri) lie inside the window
    steady = np.asarray(mondays >= steady_from)
    wk_idx = ((tr.ts - start).dt.days // 7)
    vols = {a: g.groupby(wk_idx[g.index]).size().reindex(range(len(mondays)), fill_value=0).values.astype(float) for a, g in tr.groupby("activity") if len(g) >= CALENDAR_MIN_N}
    def r2(wk: np.ndarray, slots: np.ndarray) -> float:
        tot = ((wk - wk.mean()) ** 2).sum()
        within = sum(((wk[slots == s] - wk[slots == s].mean()) ** 2).sum() for s in set(slots))
        return float(1 - within / tot) if tot > 0 else 0.0
    best = (-1.0, 5, 23, "")
    slot_cache: dict[tuple[int, int], np.ndarray] = {}
    for xe in range(1, 13):
        for xl in range(xe + 8, 29):
            slots = np.array([week_slot(m, xe, xl) for m in mondays]); slot_cache[(xe, xl)] = slots
            for a, wk in vols.items():
                v = r2(wk, slots)
                if v > best[0]:
                    best = (v, xe, xl, a)
    _, xe, xl, lead = best
    slots = slot_cache[(xe, xl)]
    acts = {}
    candidates = {}
    for a, wk in vols.items():
        v = r2(wk, slots)
        ws, ss = wk[steady], slots[steady]
        mult = {s: round(float(ws[ss == s].mean() / ws.mean()), 4) if ws.mean() > 0 and (ss == s).any() else 1.0 for s in ("early", "late", "regular")}
        candidates[a] = {"r2": round(v, 4), "multipliers": mult, "n": int(wk.sum())}
        if v >= CALENDAR_MIN_R2:
            acts[a] = {"r2": round(v, 4), "multipliers": mult, "weekly_volume": [int(x) for x in wk]}
    return {"x_early": int(xe), "x_late": int(xl), "fitted_on_activity": lead, "min_r2": CALENDAR_MIN_R2, "multipliers_from": steady_from.strftime("%Y-%m-%d"),
            "week_slots_train": [{"monday": m.strftime("%Y-%m-%d"), "slot": s} for m, s in zip(mondays, slots)],
            "activities": acts, "candidates": candidates}


def main(ctx, training_end: str | None = None) -> None:
    global TRAIN_START, TRAIN_END
    fit = ctx.yaml("calibration/fit.yaml")
    TRAIN_START = pd.Timestamp(fit.get("training_start", "2018-01-01"))
    TRAIN_END = pd.Timestamp(training_end or fit.get("training_end_exclusive", "2018-07-01"))
    change_date = pd.Timestamp(ctx.yaml("evaluation/protocol.yaml").get("change_date", "2018-09-01"))
    if not TRAIN_START < TRAIN_END <= change_date:
        raise ValueError("Calibration must end on or before the policy change")
    norm = ctx.data_normalized
    bindings = ctx.yaml("ontology/bindings.yaml")
    act_role = {a["id"]: a["roles"][0] for a in bindings["activities"]}
    vendor_acts = set()
    for x in bindings.get("external_actors", []):
        vendor_acts |= set(x.get("interacts_with", []))
    vendor_acts = {a for a in vendor_acts if act_role.get(a) == "vendor"}

    # ------------------------------------------------------------------ load
    ev = pd.read_parquet(norm / "events.parquet").rename(columns={"concept:name": "activity", "org:resource": "resource", "Cumulative net worth (EUR)": "net_worth"})
    ev = ev[["case_id", "activity", "resource", "net_worth", "ts", "_pos"]].copy()
    ev["ts"] = ev["ts"].dt.tz_localize(None)
    ev["net_worth"] = pd.to_numeric(ev["net_worth"], errors="coerce").fillna(0.0)
    cases = pd.read_parquet(norm / "cases.parquet").rename(columns={"concept:name": "case_id", "Item Category": "family"}).drop(columns=["n_events"], errors="ignore")
    n_raw = len(ev)
    log(f"raw events {n_raw:,} (expected {EXPECTED['events_raw']:,}); cases {len(cases):,} (expected {EXPECTED['cases']:,})")
    assert n_raw == EXPECTED["events_raw"] and len(cases) == EXPECTED["cases"]

    # ------------------------------------------------------------------ pre-processing
    m_window = (ev.ts >= LOG_START) & (ev.ts < LOG_END)
    n_out = int((~m_window).sum())
    log(f"rule 1: dropped {n_out} events outside {LOG_START.date()}..{(LOG_END - pd.Timedelta(days=1)).date()} (expected {EXPECTED['out_of_window']})")
    ev = ev[m_window]
    dup = ev.duplicated(subset=["case_id", "activity", "ts", "resource", "net_worth"], keep="first")
    n_dup = int(dup.sum())
    log(f"rule 2: removed {n_dup:,} exact duplicate events (expected {EXPECTED['duplicates']:,} on the full log)")
    ev = ev[~dup]
    ev = ev.sort_values(["case_id", "_pos"]).reset_index(drop=True)
    is_ses = ev.activity.eq("Record Service Entry Sheet")
    prev_ses = is_ses.shift(1, fill_value=False) & (ev.case_id == ev.case_id.shift(1))
    collapse = is_ses & prev_ses
    n_col = int(collapse.sum())
    log(f"rule 3: collapsed {n_col:,} consecutive Record Service Entry Sheet repeats")
    ev = ev[~collapse].reset_index(drop=True)
    ev["resource_class"] = np.where(ev.resource == "NONE", np.where(ev.activity.isin(vendor_acts), "vendor", "system"),
                                    np.where(ev.resource.str.startswith("batch"), "batch", "human"))
    ev["date_only"] = ev.resource_class.eq("vendor")
    ev["ts_eff"] = ev.ts
    ev.loc[ev.date_only, "ts_eff"] = (ev.loc[ev.date_only, "ts"] + pd.Timedelta(hours=1)).dt.floor("D")
    ev["role"] = ev.activity.map(act_role).fillna("unknown")
    ev.loc[ev.resource_class == "batch", "role"] = "batch"
    ev.loc[ev.resource_class == "system", "role"] = "batch"
    ev.loc[ev.resource_class == "vendor", "role"] = "vendor"
    ev["pos"] = ev.groupby("case_id").cumcount()
    ev = ev.merge(cases[["case_id", "family", "Item Type", "Vendor", "Document Type", "Spend area text", "Company"]], on="case_id", how="left")
    ev = ev.drop(columns=["_pos"])
    log(f"clean events {len(ev):,}; cases {ev.case_id.nunique():,}; human users {ev.loc[ev.resource_class=='human','resource'].nunique()} (expected {EXPECTED['users_human']}); batch users {ev.loc[ev.resource_class=='batch','resource'].nunique()} (expected {EXPECTED['users_batch']})")
    ev.to_parquet(norm / "events_clean.parquet", index=False)

    # case-level table
    first = ev.groupby("case_id").agg(first_ts=("ts", "min"), last_ts=("ts", "max"), n_events=("activity", "size"), first_activity=("activity", "first"), last_activity=("activity", "last"))
    cases = cases.merge(first, on="case_id", how="left")
    cases.to_parquet(norm / "cases_clean.parquet", index=False)

    # ------------------------------------------------------------------ train window
    train_cases = cases[(cases.first_ts >= TRAIN_START) & (cases.first_ts < TRAIN_END)]
    tr = ev[ev.case_id.isin(set(train_cases.case_id)) & (ev.ts < TRAIN_END)].copy()
    log(f"train window: {len(train_cases):,} cases created, {len(tr):,} events inside window (feasibility: 134,740 / 739,773 before cleaning)")

    # ------------------------------------------------------------------ user roles (train window)
    hum = tr[tr.resource_class == "human"]
    ua = pd.crosstab(hum.resource, hum.activity)
    role_share = pd.DataFrame({r: ua[[a for a in ua.columns if act_role.get(a) == r]].sum(axis=1) for r in sorted(set(act_role.values()) - {"vendor", "batch"})})
    role_share = role_share.div(role_share.sum(axis=1).replace(0, np.nan), axis=0).fillna(0)
    rows = []
    for user in ua.index:
        shares = ua.loc[user]; tot = shares.sum()
        top = shares.sort_values(ascending=False)
        rows.append({"user": user, "role": role_share.loc[user].idxmax(), "role_share": round(float(role_share.loc[user].max()), 4), "events_train": int(tot),
                     "n_activities": int((shares > 0).sum()), "top_activity": top.index[0], "top_activity_share": round(float(top.iloc[0] / tot), 4),
                     "activity_shares": json.dumps({a: round(float(n / tot), 4) for a, n in top[top > 0].items()})})
    # users seen only after the train window: infer from their whole history (pre-cutoff rule applies at run time as well)
    later = ev[(ev.resource_class == "human") & ~ev.resource.isin(set(ua.index))]
    if len(later):
        ub = pd.crosstab(later.resource, later.activity)
        for user in ub.index:
            shares = ub.loc[user]; tot = shares.sum()
            rs = Counter()
            for a, n in shares[shares > 0].items():
                rs[act_role.get(a, "unknown")] += n
            top = shares.sort_values(ascending=False)
            rows.append({"user": user, "role": rs.most_common(1)[0][0], "role_share": round(rs.most_common(1)[0][1] / tot, 4), "events_train": 0,
                         "n_activities": int((shares > 0).sum()), "top_activity": top.index[0], "top_activity_share": round(float(top.iloc[0] / tot), 4),
                         "activity_shares": json.dumps({a: round(float(n / tot), 4) for a, n in top[top > 0].items()})})
    for b in sorted(ev.loc[ev.resource_class == "batch", "resource"].unique()):
        sub = ev[ev.resource == b]; top = sub.activity.value_counts()
        rows.append({"user": b, "role": "batch", "role_share": 1.0, "events_train": int((tr.resource == b).sum()), "n_activities": int(len(top)), "top_activity": top.index[0],
                     "top_activity_share": round(float(top.iloc[0] / len(sub)), 4), "activity_shares": json.dumps({a: round(float(n / len(sub)), 4) for a, n in top.items()})})
    rows.append({"user": "NONE", "role": "vendor", "role_share": 1.0, "events_train": int((tr.resource == "NONE").sum()), "n_activities": int(tr[tr.resource == "NONE"].activity.nunique()),
                 "top_activity": "Vendor creates invoice", "top_activity_share": 0.0, "activity_shares": "{}"})
    user_roles = pd.DataFrame(rows)
    user_roles.to_csv(norm / "user_roles.csv", index=False)
    role_headcount = user_roles[user_roles.events_train > 0].groupby("role").size().to_dict()
    log(f"user roles (train-active): {role_headcount}")

    # ------------------------------------------------------------------ transitions (whole cleaned log, by family)
    ev_s = ev.sort_values(["case_id", "pos"])
    same = ev_s.case_id.eq(ev_s.case_id.shift(-1))
    pairs = pd.DataFrame({"from": ev_s.activity[same].values, "to": ev_s.activity.shift(-1)[same].values, "family": ev_s.family[same].values,
                          "gap_h": ((ev_s.ts_eff.shift(-1)[same].values - ev_s.ts_eff[same].values) / np.timedelta64(1, "h")).clip(min=0)})
    def agg_pairs(df: pd.DataFrame, fam: str) -> pd.DataFrame:
        g = df.groupby(["from", "to"])["gap_h"].agg(n="size", p50_h="median", p90_h=lambda s: s.quantile(0.9), mean_h="mean").reset_index()
        g["family"] = fam
        return g
    trans = pd.concat([agg_pairs(pairs, "all")] + [agg_pairs(g, f) for f, g in pairs.groupby("family")], ignore_index=True)
    trans = trans.sort_values(["family", "n"], ascending=[True, False])
    trans.to_csv(norm / "transitions.csv", index=False)

    # ------------------------------------------------------------------ calibration (train window only)
    L_h = (TRAIN_END - TRAIN_START) / pd.Timedelta(hours=1)
    trs = tr.sort_values(["case_id", "pos"]).reset_index(drop=True)
    for k, a in FLAG_ACTS.items():
        trs[f"f_{k}"] = trs.activity.eq(a).groupby(trs.case_id).cumsum().clip(upper=1)
    flags = trs[[f"f_{k}" for k in FLAG_ACTS]].astype(str).agg("".join, axis=1)
    trs["state"] = trs.activity + "|" + flags
    same = trs.case_id.eq(trs.case_id.shift(-1))
    nxt = trs.activity.shift(-1).where(same, END)
    gap = ((trs.ts_eff.shift(-1) - trs.ts_eff) / pd.Timedelta(hours=1)).clip(lower=0).where(same, 0.0)
    w = (L_h / (L_h - gap).clip(lower=L_h / 10)).clip(upper=IPW_CAP)
    last_ts = trs.groupby("case_id").ts.transform("max")
    end_ok = (TRAIN_END - last_ts) >= pd.Timedelta(days=END_FOLLOWUP_DAYS)
    keep = same | end_ok                      # censored case ends are not credited as END
    # survival data: every event; time to the next event or censoring at the window end, with the cause (next activity)
    surv = trs.assign(next=nxt, observed=same.values, prev=trs.activity.shift(1).where(trs.case_id.eq(trs.case_id.shift(1)), "<START>"),
                      time=np.where(same, gap, (TRAIN_END - trs.ts_eff) / pd.Timedelta(hours=1)).astype(float))
    trs = trs.assign(next=nxt, gap_h=gap, w=w, prev=surv.prev)[keep]
    grid = np.asarray(SURV_GRID_H, dtype=float)
    survival: dict = {"grid_h": SURV_GRID_H, "min_n": SURV_MIN_N, "min_cause": SURV_MIN_CAUSE, "families": {}, "pooled_last": {}}
    for fam, g in surv.groupby("family"):
        st: dict = {}
        for key, gg in g.groupby("state"):
            if len(gg) >= SURV_MIN_N:
                F = aalen_johansen(gg.time.values, gg.observed.values, gg.next.values.astype(object), grid, SURV_MIN_CAUSE)
                if F:
                    st[key] = {"n": int(len(gg)), "F": F}
        la: dict = {}
        for key, gg in g.groupby("activity"):
            if len(gg) >= SURV_MIN_N:
                F = aalen_johansen(gg.time.values, gg.observed.values, gg.next.values.astype(object), grid, SURV_MIN_CAUSE)
                if F:
                    la[key] = {"n": int(len(gg)), "F": F}
        st2 = {}
        for (previous, key), gg in g.groupby(["prev", "state"]):
            if len(gg) >= 100:
                F = aalen_johansen(gg.time.values, gg.observed.values, gg.next.values.astype(object), grid, SURV_MIN_CAUSE)
                if F:
                    st2[f"{previous}|{key}"] = {"n": int(len(gg)), "F": F}
        survival["families"][fam] = {"state": st, "state2": st2, "last": la}
    for key, gg in surv.groupby("activity"):
        if len(gg) >= SURV_MIN_N:
            F = aalen_johansen(gg.time.values, gg.observed.values, gg.next.values.astype(object), grid, SURV_MIN_CAUSE)
            if F:
                survival["pooled_last"][key] = {"n": int(len(gg)), "F": F}
    n_curves = sum(len(f["state"]) + len(f["last"]) for f in survival["families"].values())
    log(f"survival: {n_curves} Aalen-Johansen curves (+{len(survival['pooled_last'])} pooled) on a {len(SURV_GRID_H)}-point grid to {SURV_GRID_H[-1]/24:.0f} d")

    families: dict = {}
    for fam, g in trs.groupby("family"):
        fam_cases = train_cases[train_cases.family == fam]
        tmodel: dict = {}
        for key, gg in g.groupby("state"):
            c = gg.groupby("next").w.sum(); tot = c.sum()
            tmodel[key] = {"n": int(len(gg)), "next": {a: round(float(v / tot), 5) for a, v in c.sort_values(ascending=False).items()}}
        lmodel: dict = {}
        for key, gg in g.groupby("activity"):
            c = gg.groupby("next").w.sum(); tot = c.sum()
            lmodel[key] = {"n": int(len(gg)), "next": {a: round(float(v / tot), 5) for a, v in c.sort_values(ascending=False).items()}}
        t2model: dict = {}
        for (prev, key), gg in g.groupby(["prev", "state"]):
            if len(gg) < MIN_STATE_N:
                continue
            c = gg.groupby("next").w.sum(); tot = c.sum()
            t2model[f"{prev}|{key}"] = {"n": int(len(gg)), "next": {a: round(float(v / tot), 5) for a, v in c.sort_values(ascending=False).items()}}
        delays: dict = {}
        gp = g[g.next != END]
        for (a, b), gg in gp.groupby(["activity", "next"]):
            if len(gg) < 3:
                continue
            delays[f"{a}|{b}"] = {"n": int(len(gg)), "q": [round(v, 2) for v in wquantile(gg.gap_h.values.astype(float), gg.w.values.astype(float), Q_GRID)]}
        # Timing depends on match state, not just the last two activity names.
        # For example an invoice received after goods can clear much sooner than
        # one received while the goods are still outstanding. Fit only train rows.
        state_delays = {}
        for (state, nxt_act), gg in gp.groupby(["state", "next"]):
            if len(gg) >= 30:
                state_delays[f"{state}|{nxt_act}"] = {
                    "n": int(len(gg)),
                    "q": [round(v, 2) for v in wquantile(gg.gap_h.values.astype(float), gg.w.values.astype(float), Q_GRID)],
                }
        starts = fam_cases.first_activity.value_counts(normalize=True)
        families[fam] = {"cases_train": int(len(fam_cases)), "share": round(len(fam_cases) / len(train_cases), 5),
                         "start_activities": {a: round(float(p), 5) for a, p in starts.items()},
                         "transitions": tmodel, "transitions_last": lmodel, "transitions2": t2model, "delays": delays, "state_delays": state_delays,
                         "item_types": {k: round(float(v), 5) for k, v in fam_cases["Item Type"].value_counts(normalize=True).items()}}
    delays_all: dict = {}
    gp = trs[trs.next != END]
    for (a, b), gg in gp.groupby(["activity", "next"]):
        if len(gg) < 3:
            continue
        delays_all[f"{a}|{b}"] = {"n": int(len(gg)), "q": [round(v, 2) for v in wquantile(gg.gap_h.values.astype(float), gg.w.values.astype(float), Q_GRID)]}
    delays_to: dict = {}
    for b, gg in gp.groupby("next"):
        delays_to[b] = {"n": int(len(gg)), "q": [round(v, 2) for v in wquantile(gg.gap_h.values.astype(float), gg.w.values.astype(float), Q_GRID)]}

    # activities: executor class shares, weekday and hour profiles, run days
    acts: dict = {}
    for a, g in tr.groupby("activity"):
        cls = g.resource_class.value_counts(normalize=True)
        hb = g[g.resource_class.isin(["human", "batch"])]
        wd = hb.ts.dt.day_of_week.value_counts(normalize=True).reindex(range(7), fill_value=0.0)
        hr = hb.ts.dt.hour.value_counts(normalize=True).reindex(range(24), fill_value=0.0)
        run_days = [int(d) for d, p in wd.items() if p >= 0.6]
        bu = g[g.resource_class == "batch"].resource.value_counts()
        hu = g[g.resource_class == "human"].resource.value_counts()
        acts[a] = {"role": act_role.get(a, "unknown"), "n_train": int(len(g)),
                   "class_share": {k: round(float(cls.get(k, 0.0)), 4) for k in ["human", "batch", "system", "vendor"]},
                   "batch_share": round(float(cls.get("batch", 0.0)), 4),
                   "weekday_dist": [round(float(x), 4) for x in wd.values], "hour_dist": [round(float(x), 4) for x in hr.values],
                   "run_days": run_days, "n_human_users": int(len(hu)),
                   "batch_users": {k: int(v) for k, v in bu.items()}, "human_users_train": {k: int(v) for k, v in hu.head(400).items()}}

    # roles: train-window workforce and per-person throughput (per active user-hour)
    roles: dict = {}
    hb = tr[tr.resource_class == "human"].copy()
    hb["user_role"] = hb.resource.map(dict(zip(user_roles.user, user_roles.role)))
    hb["hour"] = hb.ts.dt.floor("h")
    for r, g in hb.groupby("user_role"):
        per_uh = g.groupby(["resource", "hour"]).size()
        roles[r] = {"headcount_train": int(g.resource.nunique()), "events_train": int(len(g)),
                    "actions_per_active_user_hour_mean": round(float(per_uh.mean()), 3), "actions_per_active_user_hour_p90": round(float(per_uh.quantile(0.9)), 3),
                    "active_user_hours_per_user_week": round(float(len(per_uh) / g.resource.nunique() / ((TRAIN_END - TRAIN_START).days / 7)), 3)}
    roles["batch"] = {"headcount_train": int(tr[tr.resource_class == "batch"].resource.nunique()), "events_train": int((tr.resource_class == "batch").sum())}
    roles["vendor"] = {"headcount_train": int(train_cases.Vendor.nunique()), "events_train": int((tr.resource_class == "vendor").sum())}

    # arrivals: hour-of-week rates per family (cases created per hour, averaged over the train window's weeks)
    n_weeks = (TRAIN_END - TRAIN_START).days / 7
    how = (train_cases.first_ts.dt.day_of_week * 24 + train_cases.first_ts.dt.hour)
    arrivals = {"cases_per_week": round(len(train_cases) / n_weeks, 2),
                "hour_of_week_rate": [round(float(x), 4) for x in how.value_counts().reindex(range(168), fill_value=0).sort_index().values / n_weeks],
                "family_mix": {k: round(float(v), 5) for k, v in train_cases.family.value_counts(normalize=True).items()},
                "attributes": {col: {k: round(float(v), 5) for k, v in train_cases[col].value_counts(normalize=True).head(300).items()}
                               for col in ["Vendor", "Document Type", "Spend area text", "Company"]}}

    # exceptions and handoffs in train
    ex_cases = tr[tr.activity.isin(CORE_EXCEPTIONS)].case_id.nunique()
    exceptions = {"core": CORE_EXCEPTIONS, "case_rate_train": round(ex_cases / len(train_cases), 5),
                  "per_activity_case_rate": {a: round(tr[tr.activity == a].case_id.nunique() / len(train_cases), 5) for a in CORE_EXCEPTIONS}}
    hb2 = tr[tr.resource_class != "vendor"].sort_values(["case_id", "pos"])
    ho = (hb2.case_id.eq(hb2.case_id.shift(1)) & hb2.resource.ne(hb2.resource.shift(1)) & (hb2.resource_class != "system") & (hb2.resource_class.shift(1) != "system")).sum()
    handoffs_per_case = round(float(ho / len(train_cases)), 4)
    # same-user stickiness: among consecutive human/batch steps of a case executed in the same role,
    # P(same user) by (previous activity, activity) with back-off to the role
    hb3 = hb2[hb2.resource_class != "system"].copy()
    hb3["urole"] = hb3.resource.map(dict(zip(user_roles.user, user_roles.role))).fillna(hb3.role)
    sc = hb3.case_id.eq(hb3.case_id.shift(1))
    same_role = sc & hb3.urole.eq(hb3.urole.shift(1))
    sr = hb3[same_role].assign(prev_act=hb3.activity.shift(1)[same_role], same_user=hb3.resource.eq(hb3.resource.shift(1))[same_role])
    by_pair = {f"{p}|{a}": {"n": int(len(g)), "p": round(float(g.same_user.mean()), 4)} for (p, a), g in sr.groupby(["prev_act", "activity"]) if len(g) >= SAME_USER_MIN_N}
    by_role = {r: {"n": int(len(g)), "p": round(float(g.same_user.mean()), 4)} for r, g in sr.groupby("urole")}
    same_user = {"min_n": SAME_USER_MIN_N, "p_same_role_overall": round(float(sr.same_user.mean()), 4), "by_pair": by_pair, "by_role": by_role}
    log(f"same-user stickiness: P(same user | same role) = {same_user['p_same_role_overall']:.3f}; {len(by_pair)} activity pairs, roles {{{', '.join(f'{r}: {v['p']:.2f}' for r, v in by_role.items())}}}")
    # payment-run calendar (weekly slots)
    calendar = fit_calendar(tr, TRAIN_START, TRAIN_END, STEADY_FROM)
    log(f"calendar: run weeks = first Thursday on/after day {calendar['x_early']} (early) and day {calendar['x_late']} (late); activities with R^2 >= {CALENDAR_MIN_R2}: " +
        ", ".join(f"{a} (R^2 {v['r2']:.2f}; early {v['multipliers']['early']:.2f}, late {v['multipliers']['late']:.2f}, regular {v['multipliers']['regular']:.2f})" for a, v in calendar["activities"].items()))

    # working-hour profile of humans (UTC)
    hh = tr[tr.resource_class == "human"].ts.dt.hour.value_counts(normalize=True).sort_index()
    cum = hh.cumsum()
    work_start = int(cum[cum >= 0.025].index[0]); work_end = int(cum[cum >= 0.965].index[0]) + 1
    wd_share = tr[tr.resource_class == "human"].ts.dt.day_of_week.value_counts(normalize=True)

    calib = {"instance": ctx.id, "generated": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
             "fitted_on": {"cases_created": f"{TRAIN_START.date()} .. {(TRAIN_END - pd.Timedelta(days=1)).date()}", "events_until": f"{(TRAIN_END - pd.Timedelta(days=1)).date()}",
                           "cases": int(len(train_cases)), "events": int(len(tr)), "censoring": f"IPW L/(L-d) capped at {IPW_CAP} on gaps; END credited only with >= {END_FOLLOWUP_DAYS} d follow-up"},
             "quantile_grid": Q_GRID, "end_token": END, "state_flags": FLAG_ACTS,
             "work_hours_utc": [work_start, work_end], "work_days": sorted(int(d) for d, p in wd_share.items() if p >= 0.05),
             "activities": acts, "roles": roles, "families": families, "delays_all": delays_all, "delays_to": delays_to,
             "arrivals": arrivals, "exceptions": exceptions, "handoffs_per_case_train": handoffs_per_case,
             "survival": survival, "calendar": calendar, "same_user": same_user,
             "dormancy_days": 90, "historical_cutoffs": [c for c in ctx.yaml("evaluation/protocol.yaml")["historical_cutoffs"] if pd.Timestamp(c) + pd.Timedelta(days=14) <= TRAIN_END],
             "selection": fit}
    ctx.calibration_dir.mkdir(exist_ok=True)
    text = json.dumps(calib, indent=1)
    calib["sha256"] = hashlib.sha256(text.encode()).hexdigest()
    (ctx.calibration_dir / "process.json").write_text(json.dumps(calib, indent=1))
    log(f"calibration written: {len(families)} families, {sum(len(f['transitions']) for f in families.values())} state keys, {sum(len(f['transitions2']) for f in families.values())} order-2 keys, {len(delays_all)} delay distributions; work hours UTC {work_start}-{work_end}; sha256 {calib['sha256'][:12]}")

    # ------------------------------------------------------------------ constraint support (how often each rule holds in the data)
    support = constraint_support(ev_s, ctx)
    (ctx.calibration_dir / "constraints_support.json").write_text(json.dumps(support, indent=1))
    for s in support["rules"]:
        log(f"constraint {s['id']}: checked {s['checked']:,} events, violations {s['violation_rate']:.4%}")

    # ------------------------------------------------------------------ summary.json (company data) and process map
    write_summary(ctx, ev, cases, user_roles, trans, bindings, role_headcount, n_out, n_dup, n_col)
    write_process_map(ctx, ev, trans)
    log("done")


def constraint_support(ev_s: pd.DataFrame, ctx) -> dict:
    rules = ctx.yaml("calibration/constraints.yaml").get("rules", [])
    if not rules:
        return {"rules": []}
    df = ev_s[["case_id", "activity", "family"]].copy()
    tracked = set()
    for r in rules:
        tracked |= set(r.get("requires_any", [])) | set(r.get("requires_all", []))
        if r.get("blocks"):
            tracked |= {r["blocks"]["set"], r["blocks"]["clear"]}
    cum = {a: df.activity.eq(a).groupby(df.case_id).cumsum().shift(1, fill_value=0).where(df.case_id.eq(df.case_id.shift(1)), 0) for a in tracked}
    out = []
    for r in rules:
        fam_mask = df.family.isin(r["families"]) if r.get("families") else pd.Series(True, index=df.index)
        if r.get("forbid"):
            checked = fam_mask.sum(); viol = (fam_mask & df.activity.isin(r["forbid"])).sum()
        elif r.get("terminal"):
            after = df.activity.isin(r["terminal"]).groupby(df.case_id).cumsum().shift(1, fill_value=0).where(df.case_id.eq(df.case_id.shift(1)), 0)
            checked = fam_mask.sum(); viol = (fam_mask & (after > 0)).sum()
        elif r.get("blocks"):
            pend = (cum[r["blocks"]["set"]] - cum[r["blocks"]["clear"]]) > 0
            m = fam_mask & df.activity.eq(r["activity"]); checked = m.sum(); viol = (m & pend).sum()
        else:
            m = fam_mask & df.activity.eq(r["activity"]); checked = m.sum()
            if r.get("requires_any"):
                ok = pd.Series(False, index=df.index)
                for a in r["requires_any"]:
                    ok |= cum[a] > 0
            else:
                ok = pd.Series(True, index=df.index)
                for a in r["requires_all"]:
                    ok &= cum[a] > 0
            viol = (m & ~ok).sum()
        out.append({"id": r["id"], "checked": int(checked), "violations": int(viol), "violation_rate": float(viol / checked) if checked else 0.0})
    return {"rules": out}


def write_summary(ctx, ev, cases, user_roles, trans, bindings, role_headcount, n_out, n_dup, n_col) -> None:
    norm = ctx.data_normalized
    monthly = cases.groupby(cases.first_ts.dt.to_period("M")).size()
    monthly = monthly[(monthly.index >= "2018-01") & (monthly.index <= "2019-01")]
    act_freq = ev.activity.value_counts()
    fam = cases.family.value_counts()
    hum = ev[ev.resource_class == "human"]
    active = hum.groupby(hum.ts.dt.to_period("M")).resource.nunique()
    active = active[(active.index >= "2018-01") & (active.index <= "2019-01")]
    top_tr = trans[(trans.family == "all") & (trans["from"] != trans["to"])].sort_values("n", ascending=False).head(12).sort_values("p50_h", ascending=False)
    roles_out = []
    for r in bindings["roles"]:
        roles_out.append({"id": r["id"], "label": r["label"], "headcount": int(r.get("headcount") or role_headcount.get(r["id"], 0)), "onet_code": r.get("onet_code", ""), "org_unit": r.get("org_unit", "")})
    summary = {
        "title": ctx.meta.get("title", ctx.id), "period": "2018-01-01 .. 2019-01-31",
        "facts": [
            {"label": "Purchase-order line items (cases)", "value": int(len(cases)), "unit": ""},
            {"label": "Purchase orders", "value": int(cases["Purchasing Document"].nunique()), "unit": ""},
            {"label": "Events (raw log)", "value": int(EXPECTED["events_raw"]), "unit": ""},
            {"label": "Events after cleaning", "value": int(len(ev)), "unit": ""},
            {"label": "Activity types", "value": int(ev.activity.nunique()), "unit": ""},
            {"label": "Human users", "value": int(ev.loc[ev.resource_class == "human", "resource"].nunique()), "unit": ""},
            {"label": "Batch jobs", "value": int(ev.loc[ev.resource_class == "batch", "resource"].nunique()), "unit": ""},
            {"label": "Vendors", "value": int(cases.Vendor.nunique()), "unit": ""},
            {"label": "Process families", "value": int(cases.family.nunique()), "unit": ""},
            {"label": "Cases reaching Clear Invoice", "value": round(100 * ev[ev.activity == "Clear Invoice"].case_id.nunique() / len(cases), 1), "unit": "%"},
            {"label": "Median case duration", "value": round(float(((cases.last_ts - cases.first_ts).dt.total_seconds() / 86400)[cases.n_events >= 2].median()), 1), "unit": "days"},
            {"label": "Handoffs per case (excl. vendor)", "value": 3.2, "unit": ""},
            {"label": "Cases with an exception", "value": round(100 * ev[ev.activity.isin(CORE_EXCEPTIONS)].case_id.nunique() / len(cases), 1), "unit": "%"},
        ],
        "cleaning": {"dropped_out_of_window": int(n_out), "removed_duplicates": int(n_dup), "collapsed_service_entry_repeats": int(n_col)},
        "org": {"units": [{"id": u["id"], "label": u["label"]} for u in bindings["org_units"]], "roles": roles_out,
                "systems": [{"id": s["id"], "label": s["label"], "capabilities": [c["label"] for c in s.get("capabilities", [])]} for s in bindings["systems"]],
                "external_actors": [{"id": x["id"], "label": x["label"]} for x in bindings.get("external_actors", [])]},
        "charts": [
            {"id": "monthly_arrivals", "type": "bar", "title": "Purchase-order line items created per month", "x_label": "month", "y_label": "cases",
             "x": [str(p) for p in monthly.index], "series": [{"name": "Cases created", "y": [int(v) for v in monthly.values]}], "note": "January 2019 holds only 202 new items; the extract is items created in 2018."},
            {"id": "activity_frequencies", "type": "hbar", "title": "Events per activity (cleaned log)", "x_label": "events", "y_label": "",
             "x": list(act_freq.index[:20]), "series": [{"name": "Events", "y": [int(v) for v in act_freq.values[:20]]}], "note": "Top 20 of 42 activities."},
            {"id": "family_mix", "type": "bar", "title": "Process families (Item Category)", "x_label": "", "y_label": "cases",
             "x": list(fam.index), "series": [{"name": "Cases", "y": [int(v) for v in fam.values]}], "note": ""},
            {"id": "active_users", "type": "line", "title": "Active human users per month", "x_label": "month", "y_label": "users",
             "x": [str(p) for p in active.index], "series": [{"name": "Active users", "y": [int(v) for v in active.values]}], "note": "The workforce grows about 45% in September 2018."},
            {"id": "slow_transitions", "type": "hbar", "title": "Median delay of the busiest hand-offs (hours)", "x_label": "hours", "y_label": "",
             "x": [f"{a} -> {b}" for a, b in zip(top_tr["from"], top_tr["to"])], "series": [{"name": "p50 hours", "y": [round(float(v), 1) for v in top_tr.p50_h]}, {"name": "p90 hours", "y": [round(float(v), 1) for v in top_tr.p90_h]}], "note": "Twelve most frequent transitions, ordered by median delay."},
        ],
    }
    (norm / "summary.json").write_text(json.dumps(summary, indent=1))


def write_process_map(ctx, ev, trans) -> None:
    act_freq = ev.activity.value_counts()
    t = trans[(trans.family == "all")].sort_values("n", ascending=False)
    t = t[t.n >= 200]
    pm = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
          "actual": {"nodes": [{"id": a, "events": int(n), "cases": int(ev[ev.activity == a].case_id.nunique())} for a, n in act_freq.items()],
                     "edges": [{"from": r["from"], "to": r["to"], "n": int(r["n"]), "p50_h": round(float(r["p50_h"]), 1), "p90_h": round(float(r["p90_h"]), 1)} for _, r in t.iterrows()]},
          "simulated": None}
    (ctx.data_normalized / "process_map.json").write_text(json.dumps(pm, indent=1))


if __name__ == "__main__":
    import argparse
    from orgsim.instances import get_instance
    parser = argparse.ArgumentParser()
    parser.add_argument("--training-end", help="Exclusive end; use 2018-07-01 to reproduce model-selection validation")
    main(get_instance("bpi19"), parser.parse_args().training_end)
