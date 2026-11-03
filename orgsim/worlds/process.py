"""Hourly purchase-to-pay simulation with censoring-aware event timing.

The instance supplies activities, roles, constraints and calibrated distributions.
The configured joint timing model uses Aalen-Johansen cumulative incidence by
family, previous activity, last activity and match state. Unobserved follow-up
remains survival mass, rather than a fabricated terminal outcome. Calendar
multipliers act on cause-specific hazards among cases still waiting. Both next
activity and delay are drawn from the same conditional distribution, given the
elapsed wait at the prediction cutoff. Sparse states back off to broader groups.

Human actions queue for role capacity measured from the prefix. Executor roles
are inferred only from pre-cutoff events, and the same-user model preserves
continuity. C-I supplies actual arrivals as an exogenous input while hiding all
of their subsequent events; C-II samples arrivals from historical rates.

Only after-change runs are scored. Actual and simulated business metrics share
one eligible-case population and one time window. Alternatives use exactly the
same cutoffs and seeds. Evaluation records the run cohort, per-window errors and
non-simulation comparators; the Results view never mixes unrelated runs.

World switches: state_order, state_timing, t0_timing (joint, ipw or aj), calendar,
calendar_mode (hazard or density), same_user. The instance scenario pins the
selected configuration. Interventions: capacity/headcount_shift by role,
automate an activity, multiply its delay, exception_rate or arrival_multiplier.
"""
from __future__ import annotations

import json
import math
import multiprocessing
import time
from concurrent.futures import ProcessPoolExecutor
from functools import lru_cache
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..evaluation import MarkovNextActivity, accuracy, interval, jensen_shannon, log_loss, rank_correlation
from ..instances import InstanceContext
from ..kernel import Agent, CapacityPool, RunSummary, WorkItem
from ..kernel.world import BaseWorld
from ..scenarios.assistance import assistance_by_activity
from ..policies import Action, Observation, load_registry
from ..scenarios import load_scenario
from ..store import RunWriter
from ..store.trace import TraceEvent
from .survival import week_slot

HOUR = timedelta(hours=1)
END = "<END>"
MIN_STATE_N = 20          # use the state-flag transition row only if it has this many observations
DEFAULT_Q = [0.0, 0.02, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 0.98, 0.99]

_EVENTS_CACHE: dict[str, tuple[float, pd.DataFrame, pd.DataFrame]] = {}


def load_events(ctx: InstanceContext) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Cleaned events and cases (cached per process)."""
    p = ctx.data_normalized / "events_clean.parquet"
    if not p.exists():
        raise FileNotFoundError(f"{p} missing: run `orgsim ingest {ctx.id}` first")
    mt = p.stat().st_mtime
    hit = _EVENTS_CACHE.get(str(p))
    if hit and hit[0] == mt:
        return hit[1], hit[2]
    ev = pd.read_parquet(p, columns=["case_id", "activity", "resource", "resource_class", "role", "ts", "ts_eff", "pos", "family"])
    cases = pd.read_parquet(ctx.data_normalized / "cases_clean.parquet")
    ev = ev.sort_values(["case_id", "pos"]).reset_index(drop=True)
    _EVENTS_CACHE[str(p)] = (mt, ev, cases)
    return ev, cases


# --------------------------------------------------------------------------- calibration helpers
class Calibration:
    def __init__(self, raw: dict[str, Any]) -> None:
        self.raw = raw
        self.q_grid = np.asarray(raw.get("quantile_grid", DEFAULT_Q), dtype=float)
        self.families = raw["families"]
        self.activities = raw["activities"]
        self.delays_all = raw.get("delays_all", {})
        self.delays_to = raw.get("delays_to", {})
        self.flags = raw.get("state_flags", {})
        self.work_hours = tuple(raw.get("work_hours_utc", [8, 18]))
        self.work_days = tuple(raw.get("work_days", [0, 1, 2, 3, 4]))
        self.default_family = max(self.families, key=lambda f: self.families[f].get("share", 0))
        self._qcache: dict[tuple[str, str, str], np.ndarray] = {}
        # v2: Aalen-Johansen cumulative incidence per (family, state | last activity), payment-run calendar, same-user stickiness
        self.survival = raw.get("survival") or {}
        self.surv_grid = np.asarray(self.survival.get("grid_h", []), dtype=float)
        self.backoff_k = float(raw.get("backoff_k", MIN_STATE_N))          # pseudo-count of the order-1 row when interpolating the order-2 row
        self.surv_min_events = int(raw.get("survival_min_events", 100))    # observed events of a cause needed to use its curve
        self.surv_cap = float(self.q_grid[-1])                              # conditional CDF is capped like the IPW grid (p99)
        self._gcache: dict[tuple, tuple[np.ndarray, str] | None] = {}
        self.same_user = raw.get("same_user") or {}
        self.calendar = raw.get("calendar") or {}
        self.cal_origin = pd.Timestamp("2017-12-01")
        self.cal_mult: dict[str, np.ndarray] = {}
        if self.calendar.get("activities"):
            days = pd.date_range(self.cal_origin, "2019-06-30", freq="D")
            mondays = days - pd.to_timedelta(days.day_of_week, unit="D")
            slots = [week_slot(m, int(self.calendar["x_early"]), int(self.calendar["x_late"])) for m in mondays]
            for a, info in self.calendar["activities"].items():
                self.cal_mult[a] = np.asarray([info["multipliers"][sl] for sl in slots], dtype=float)
        self.day_grid_h = np.arange(0, 182) * 24.0        # day boundaries for the calendar discretisation (0 .. 181 d)
        # pooled last-activity model across families (fallback for unseen (family, activity) rows)
        pooled: dict[str, Counter] = defaultdict(Counter)
        for fam in self.families.values():
            for a, row in fam["transitions_last"].items():
                for b, p in row["next"].items():
                    pooled[a][b] += p * row["n"]
        self.pooled_last = {a: {b: v / sum(c.values()) for b, v in c.items()} for a, c in pooled.items()}

    def family(self, fam: str) -> dict[str, Any]:
        return self.families.get(fam) or self.families[self.default_family]

    def state_key(self, last: str, counts: Counter) -> str:
        return last + "|" + "".join("1" if counts.get(a, 0) > 0 else "0" for a in self.flags.values())

    def next_probs(self, fam: str, last: str, counts: Counter, prev: str | None = None, order: int = 1) -> tuple[dict[str, float], str]:
        """Back-off chain: (previous activity, last activity, state flags) -> (last, flags) -> last -> pooled last -> END."""
        f = self.family(fam)
        key = self.state_key(last, counts)
        if order >= 2 and prev is not None:
            row2 = f.get("transitions2", {}).get(f"{prev}|{key}")
            if row2 and row2["n"] >= MIN_STATE_N:
                base, _ = self.next_probs(fam, last, counts, prev=None, order=1)
                k, n2 = float(self.backoff_k), float(row2["n"])
                mixed = {a: (n2 * row2["next"].get(a, 0.0) + k * base.get(a, 0.0)) / (n2 + k) for a in sorted(set(row2["next"]) | set(base))}
                return mixed, "state2"
        row = f["transitions"].get(key)
        if row and row["n"] >= MIN_STATE_N:
            return row["next"], "state"
        row = f["transitions_last"].get(last)
        if row and row["n"] >= 5:
            return row["next"], "last"
        if last in self.pooled_last:
            return self.pooled_last[last], "pooled"
        return {END: 1.0}, "none"

    def quantiles(self, fam: str, a: str, b: str, counts: Counter | None = None) -> np.ndarray:
        state = self.state_key(a, counts) if counts is not None else ""
        k = (fam, a, b, state)
        if k in self._qcache:
            return self._qcache[k]
        key = f"{a}|{b}"
        d = self.family(fam)["delays"].get(key) or self.delays_all.get(key) or self.delays_to.get(b)
        q = np.asarray(d["q"], dtype=float) if d else np.linspace(0, 240, len(self.q_grid))
        specific = self.family(fam).get("state_delays", {}).get(f"{state}|{b}") if state else None
        if specific:
            # Shrink sparse state estimates toward the family transition.
            weight = specific["n"] / (specific["n"] + MIN_STATE_N)
            q = weight * np.asarray(specific["q"], dtype=float) + (1 - weight) * q
        q = np.maximum.accumulate(q)
        self._qcache[k] = q
        return q

    def cdf(self, q: np.ndarray, x: float) -> float:
        if x <= q[0]:
            return 0.0
        if x >= q[-1]:
            return float(self.q_grid[-1])
        return float(np.interp(x, q, self.q_grid))

    # ---- v2 timing: Aalen-Johansen conditional gap distribution and payment-run calendar
    def gap_cdf(self, fam: str, last: str, a: str, counts: Counter) -> tuple[np.ndarray, str] | None:
        """G_a(t) = P(gap <= t | next = a) on surv_grid from the cumulative incidence F_a (state -> last -> pooled), or None."""
        key = self.state_key(last, counts)
        k = (fam, key, a)
        if k in self._gcache:
            return self._gcache[k]
        out = None
        fs = self.survival.get("families", {}).get(fam) or self.survival.get("families", {}).get(self.default_family) or {}
        for level, row in (("state", fs.get("state", {}).get(key)), ("last", fs.get("last", {}).get(last)), ("pooled", self.survival.get("pooled_last", {}).get(last))):
            F = (row or {}).get("F", {}).get(a)
            if F and F[-1] > 0 and row["n"] * F[-1] >= self.surv_min_events:      # enough observed events of this cause
                G = np.asarray(F, dtype=float) / F[-1]
                out = (np.minimum(G, self.surv_cap), level)                          # keep a tail beyond the window, as the IPW p99 cap does
                break
        self._gcache[k] = out
        return out

    def joint_row(self, fam: str, last: str, counts: Counter, prev: str | None = None) -> tuple[dict, str] | None:
        """Joint cause/time distribution, retaining censored survival mass.

        Unlike a fabricated END observation after a fixed quiet period, a
        right-censored case remains at risk until its last observable time.
        """
        fs = self.survival.get("families", {}).get(fam, {})
        key = self.state_key(last, counts)
        for level, row in (("state2", fs.get("state2", {}).get(f"{prev}|{key}")) if prev is not None else ("state2", None),
                           ("state", fs.get("state", {}).get(key)),
                           ("last", fs.get("last", {}).get(last)),
                           ("pooled", self.survival.get("pooled_last", {}).get(last))):
            if row and row["n"] >= self.surv_min_events and row.get("F"):
                return row, level
        return None

    def joint_gap(self, fam: str, last: str, a: str, counts: Counter, prev: str | None = None):
        hit = self.joint_row(fam, last, counts, prev)
        curve = hit[0]["F"].get(a) if hit else None
        return (np.asarray(curve) / curve[-1], hit[1]) if curve and curve[-1] > 0 else None

    def gap_cdf_at(self, G: tuple[np.ndarray, str] | None, q: np.ndarray, t: np.ndarray | float):
        """Conditional gap CDF at t hours: from the AJ curve when available, else from the IPW quantiles."""
        if G is not None:
            grid = G[2] if len(G) > 2 else self.surv_grid
            return np.interp(t, grid, G[0], left=0.0, right=float(G[0][-1]))
        return np.interp(t, q, self.q_grid, left=0.0, right=float(self.q_grid[-1]))

    def invert_gap_cdf(self, G: tuple[np.ndarray, str], u: float) -> float:
        return float(np.interp(u, G[0], G[2] if len(G) > 2 else self.surv_grid))

    def day_masses(self, G, q: np.ndarray, elapsed_h: float) -> tuple[np.ndarray, float]:
        """Mass of the conditional gap distribution per day k (k-th day after the last event), given gap > elapsed_h,
        plus the mass beyond the last day boundary. Not normalised."""
        b = np.maximum(self.day_grid_h, elapsed_h)
        cdf = self.gap_cdf_at(G, q, b)
        masses = np.diff(cdf)
        if elapsed_h == 0:
            masses[0] += cdf[0]  # retain same-timestamp steps for newly executed events
        return masses, float(1.0 - cdf[-1])

    def calendar_mult(self, activity: str, since: datetime) -> np.ndarray | None:
        """Calendar multiplier for days 0..180 after `since` for an activity with a fitted payment-run calendar."""
        m = self.cal_mult.get(activity)
        if m is None:
            return None
        i0 = int((pd.Timestamp(since).normalize() - self.cal_origin).days)
        i0 = min(max(i0, 0), len(m) - len(self.day_grid_h))
        return m[i0:i0 + len(self.day_grid_h) - 1]

    def p_same_user(self, prev_act: str | None, activity: str, role: str) -> float:
        su = self.same_user
        row = su.get("by_pair", {}).get(f"{prev_act}|{activity}") if prev_act else None
        if row:
            return float(row["p"])
        row = su.get("by_role", {}).get(role)
        return float(row["p"]) if row else float(su.get("p_same_role_overall", 0.0))

    def sample_delay(self, rng: np.random.Generator, q: np.ndarray, min_h: float = 0.0) -> float:
        lo = self.cdf(q, min_h) if min_h > 0 else 0.0
        u = rng.uniform(lo, 1.0)
        if u >= self.q_grid[-1]:        # beyond the last stored quantile: exponential tail from the p99
            tail = max(q[-1] - q[-2], 1.0)
            return float(max(q[-1], min_h) + rng.exponential(tail))
        return float(max(np.interp(u, self.q_grid, q), min_h))


class Constraints:
    """Rules from calibration/constraints.yaml; `allowed` is the kernel's validity check."""

    def __init__(self, raw: dict[str, Any], activity_props: dict[str, dict]) -> None:
        self.rules = raw.get("rules", [])
        self.dormancy_days = int(raw.get("dormancy_days", 90))
        self.terminal: set[str] = set()
        self.forbid: dict[str, set[str]] = defaultdict(set)         # family -> activities
        self.by_activity: dict[str, list[dict]] = defaultdict(list)
        for r in self.rules:
            if r.get("terminal"):
                self.terminal |= set(r["terminal"])
            elif r.get("forbid"):
                for fam in r.get("families", ["*"]):
                    self.forbid[fam] |= set(r["forbid"])
            else:
                self.by_activity[r["activity"]].append(r)
        for a, p in activity_props.items():
            if p.get("terminal"):
                self.terminal.add(a)

    def allowed(self, fam: str, activity: str, counts: Counter) -> tuple[bool, str]:
        if activity in self.forbid.get(fam, ()) or activity in self.forbid.get("*", ()):
            return False, "forbidden_in_family"
        for r in self.by_activity.get(activity, ()):
            if r.get("families") and fam not in r["families"]:
                continue
            if r.get("requires_any") and not any(counts.get(a, 0) > 0 for a in r["requires_any"]):
                return False, r["id"]
            if r.get("requires_all") and not all(counts.get(a, 0) > 0 for a in r["requires_all"]):
                return False, r["id"]
            if r.get("blocks") and counts.get(r["blocks"]["set"], 0) - counts.get(r["blocks"]["clear"], 0) > 0:
                return False, r["id"]
        return True, ""


def open_cases_at(ev: pd.DataFrame, cases: pd.DataFrame, t0: pd.Timestamp, dormancy_days: int, terminal: set[str], completing: set[str]) -> pd.DataFrame:
    """Prefix table of cases considered live at t0: created <= t0, not dormant, no terminal activity in the prefix.
    Returns one row per case with the prefix as a list, the last event, and flags; column `completed_before` marks
    cases that already reached a completing activity (they may still produce follow-up events)."""
    pre = ev[ev.ts <= t0]
    last = pre.groupby("case_id").ts.max()
    live = last[last >= t0 - pd.Timedelta(days=dormancy_days)].index
    pre = pre[pre.case_id.isin(live)]
    term = pre[pre.activity.isin(terminal)].case_id.unique()
    pre = pre[~pre.case_id.isin(term)]
    g = pre.groupby("case_id", sort=False)
    out = g.agg(history=("activity", list), last_activity=("activity", "last"), last_ts=("ts", "last"), last_ts_eff=("ts_eff", "last"),
                last_resource=("resource", "last"), last_class=("resource_class", "last"), last_role=("role", "last"), first_ts=("ts", "first"), n_prefix=("activity", "size"))
    comp = pre[pre.activity.isin(completing)].case_id.unique()
    out["completed_before"] = out.index.isin(comp)
    out = out.join(cases.set_index("case_id")[["family", "Item Type", "Vendor", "Document Type", "Spend area text"]], how="left")
    return out.reset_index()


class _FastTraceEvent(TraceEvent):
    """Same schema as TraceEvent; builds the row directly instead of dataclasses.asdict (10x faster for large runs)."""

    def to_row(self) -> dict[str, Any]:
        return {"tick": self.tick, "sim_time": self.sim_time, "agent_id": self.agent_id, "role": self.role, "org_unit": self.org_unit, "case_id": self.case_id,
                "activity": self.activity, "action_type": self.action_type, "duration_h": self.duration_h, "wait_h": self.wait_h, "provenance": self.provenance,
                "attributes": json.dumps(self.attributes, default=str) if self.attributes else "{}"}


# --------------------------------------------------------------------------- the world
class World(BaseWorld):
    def emit(self, **kw: Any) -> TraceEvent:
        ev = _FastTraceEvent(tick=self.clock.tick, sim_time=self.clock.now, **kw)
        self._writer.write_event(ev)
        self._n_events += 1
        return ev

    @classmethod
    def from_instance(cls, ctx: InstanceContext, scenario: dict[str, Any], seed: int) -> "World":
        w = scenario.get("world", {})
        t0 = pd.Timestamp(w.get("t0", "2018-09-03"))
        horizon = int(scenario.get("horizon_days", w.get("horizon_days", 14)))
        return cls(ctx, scenario, seed, t0.to_pydatetime(), (t0 + pd.Timedelta(days=horizon)).to_pydatetime())

    def __init__(self, ctx: InstanceContext, scenario: dict[str, Any], seed: int, start: datetime, end: datetime) -> None:
        super().__init__(ctx, scenario, seed, start, end)
        self.rng = np.random.default_rng(seed)
        self.t0 = pd.Timestamp(start)
        self.horizon_days = int(round((end - start) / timedelta(days=1)))
        self.wcfg = scenario.get("world", {})
        self.track = str(self.wcfg.get("track", "C-I"))
        self.interventions = list(scenario.get("interventions") or [])
        self.calib = Calibration(json.loads((ctx.calibration_dir / "process.json").read_text()))
        # v2 model switches (defaults = the variant selected on the validation cutoffs; see module docstring)
        self.state_order = int(self.wcfg.get("state_order", 2))
        self.t0_timing = str(self.wcfg.get("t0_timing", "ipw"))           # "ipw": quantile survival (selected); "aj": Aalen-Johansen conditional gap CDF (evaluated, not selected)
        self.use_calendar = bool(self.wcfg.get("calendar", True)) and bool(self.calib.cal_mult)
        self.use_same_user = bool(self.wcfg.get("same_user", True)) and bool(self.calib.same_user)
        self.state_timing = bool(self.wcfg.get("state_timing", True))
        self.calendar_mode = str(self.wcfg.get("calendar_mode", "density"))
        self._joint_base_cache = {}
        self._joint_current = (None, None)
        bindings = ctx.yaml("ontology/bindings.yaml")
        self.act_props: dict[str, dict] = {a["id"]: {**(a.get("properties") or {}), "roles": a.get("roles", [])} for a in bindings.get("activities", [])}
        self.assistance = assistance_by_activity(self.interventions, set(self.act_props))
        self.human_work_hours = 0.0
        self.unassisted_work_hours = 0.0
        self.ai_review_hours = 0.0
        self.ai_rework_hours = 0.0
        self.role_unit: dict[str, str] = {r["id"]: r.get("org_unit", "") for r in bindings.get("roles", [])}
        self.constraints = Constraints(ctx.yaml("calibration/constraints.yaml"), self.act_props)
        self.completing: set[str] = {a for a, p in self.act_props.items() if p.get("completes_case")}
        self.exception_acts: set[str] = set(self.calib.raw.get("exceptions", {}).get("core", [])) | {a for a, p in self.act_props.items() if p.get("exception")}
        self.external_acts: set[str] = set()
        for x in bindings.get("external_actors", []):
            self.external_acts |= {a for a in x.get("interacts_with", []) if self.calib.activities.get(a, {}).get("class_share", {}).get("vendor", 0) > 0.5}
        self.clock.work_hours = self.calib.work_hours
        self.clock.work_days = self.calib.work_days
        self.registry = load_registry(ctx)
        # intervention knobs
        self.delay_mult: dict[str, float] = defaultdict(lambda: 1.0)
        self.class_override: dict[str, dict[str, float]] = {}
        self.exception_mult = 1.0
        self.arrival_mult = float(self.wcfg.get("arrival_multiplier", 1.0))
        self.capacity_mult: dict[str, float] = defaultdict(lambda: 1.0)
        for iv in self.interventions:
            t = iv.get("type")
            if t in ("capacity", "headcount_shift"):
                self.capacity_mult[str(iv.get("role", "all"))] *= float(iv.get("multiplier", 1.0))
            elif t == "automate":
                a = iv["activity"]; bs = float(iv.get("batch_share", 1.0))
                cs = dict(self.calib.activities.get(a, {}).get("class_share", {"human": 1.0}))
                human_left = max(0.0, cs.get("human", 0.0) + cs.get("batch", 0.0) - bs)
                self.class_override[a] = {**cs, "batch": bs, "human": human_left}
                self.delay_mult[a] *= float(iv.get("delay_multiplier", 1.0))
            elif t == "delay":
                self.delay_mult[iv["activity"]] *= float(iv.get("multiplier", 1.0))
            elif t == "exception_rate":
                self.exception_mult *= float(iv.get("multiplier", 1.0))
            elif t == "arrival_multiplier":
                self.arrival_mult *= float(iv.get("multiplier", 1.0))
        # data
        self.events, self.cases_df = load_events(ctx)
        self._build_workforce()
        self._build_open_cases()
        self._build_arrivals()
        # bookkeeping for evaluation
        self.first_decision: dict[str, dict[str, float]] = {}
        self.sim_events: list[tuple] = []          # (case_id, sim_time, activity, agent_id, role, cls, wait_h)
        self.n_rejected = 0
        self.n_decisions = 0
        self.wait_samples: list[float] = []
        self.handoffs = 0
        self.completed: dict[str, datetime] = {}
        self.ended: set[str] = set()
        self.steps_this_tick: Counter = Counter()

    # ------------------------------------------------------------------ construction
    def _build_workforce(self) -> None:
        ev = self.events
        t0 = self.t0
        win = ev[(ev.ts >= t0 - pd.Timedelta(days=14)) & (ev.ts < t0)]
        hum = win[win.resource_class == "human"]
        act_role = {a: v["role"] for a, v in self.calib.activities.items()}
        # The display table includes later users' full histories. Infer execution
        # roles from the prefix instead, so no future event can change capacity.
        prefix_hum = ev[(ev.ts < t0) & (ev.resource_class == "human")]
        role_counts = prefix_hum.assign(inferred_role=prefix_hum.activity.map(act_role)).groupby(["resource", "inferred_role"]).size()
        user_roles = role_counts.groupby(level=0).idxmax().map(lambda x: x[1]).to_dict()
        self.activity_users: dict[str, tuple[list[str], np.ndarray, set[str]]] = {}
        for a, g in hum.groupby("activity"):
            c = g.resource.value_counts()
            self.activity_users[a] = (list(c.index), np.cumsum(c.values / c.values.sum()), set(c.index))
        for a, info in self.calib.activities.items():        # fallback: train-window users
            if a not in self.activity_users and info.get("human_users_train"):
                users = list(info["human_users_train"].items())
                vals = np.array([n for _, n in users], dtype=float)
                self.activity_users[a] = ([u for u, _ in users], np.cumsum(vals / vals.sum()), {u for u, _ in users})
        self.batch_users: dict[str, tuple[list[str], np.ndarray, set[str]]] = {}
        for a, info in self.calib.activities.items():
            if info.get("batch_users"):
                users = list(info["batch_users"].items()); vals = np.array([n for _, n in users], dtype=float)
                self.batch_users[a] = ([u for u, _ in users], np.cumsum(vals / vals.sum()), {u for u, _ in users})
        # role pools: active headcount and actions per active user-hour in the two weeks before t0
        hum = hum.assign(user_role=hum.resource.map(user_roles).fillna(hum.activity.map(act_role)), hour=hum.ts.dt.floor("h"))
        self.pools: dict[str, CapacityPool] = {}
        self.workforce: dict[str, dict[str, float]] = {}
        for role in sorted({v["role"] for v in self.calib.activities.values()} | set(user_roles.values())):
            if role in ("batch", "vendor"):
                continue
            g = hum[hum.user_role == role]
            ref = self.calib.raw.get("roles", {}).get(role, {})
            headcount = float(g.resource.nunique()) if len(g) else float(ref.get("headcount_train", 1))
            aph = float(g.groupby(["resource", "hour"]).size().mean()) if len(g) else float(ref.get("actions_per_active_user_hour_mean", 5.0))
            mult = self.capacity_mult["all"] * self.capacity_mult[role]
            self.pools[role] = CapacityPool(role=role, headcount=headcount * mult, actions_per_person_hour=aph)
            self.workforce[role] = {"active_headcount": headcount, "headcount_simulated": round(headcount * mult, 2), "actions_per_active_hour": round(aph, 2), "events_2w": int(len(g))}
        for role, pool in self.pools.items():
            self.agents[role] = Agent(id=role, role=role, org_unit=self.role_unit.get(role, ""), seat=role)

    def _build_open_cases(self) -> None:
        pre = open_cases_at(self.events, self.cases_df, self.t0, self.constraints.dormancy_days, self.constraints.terminal, self.completing)
        self.open_cases = pre
        n_open = 0
        for r in pre.itertuples(index=False):
            hist = list(r.history)
            item = WorkItem(id=r.case_id, kind="case", created_at=r.first_ts.to_pydatetime(), history=hist,
                            attributes={"family": r.family, "item_type": r._asdict().get("Item Type"), "vendor": r.Vendor, "document_type": r._asdict().get("Document Type"), "replayed_prefix": int(r.n_prefix)},
                            state={"counts": Counter(hist), "last_ts": r.last_ts_eff.to_pydatetime(), "last_agent": r.last_resource if r.last_class in ("human", "batch") else "",
                                   "last_role": r.last_role, "completed_before": bool(r.completed_before), "open_at_t0": True})
            self.items[r.case_id] = item
            if not r.completed_before:
                n_open += 1
        self.n_open_at_t0 = n_open
        self.n_considered_at_t0 = len(pre)

    def _build_arrivals(self) -> None:
        t0, end = self.t0, pd.Timestamp(self.clock.end)
        self.arrivals: list[dict[str, Any]] = []
        if self.track.upper().startswith("C-I") and not self.track.upper().startswith("C-II"):
            c = self.cases_df[(self.cases_df.first_ts > t0) & (self.cases_df.first_ts <= end)]
            for r in c.itertuples(index=False):
                self.arrivals.append({"case_id": r.case_id, "when": r.first_ts.to_pydatetime(), "activity": r.first_activity, "family": r.family,
                                      "attrs": {"item_type": r._asdict().get("Item Type"), "vendor": r.Vendor, "document_type": r._asdict().get("Document Type")}, "provenance": "replayed"})
        else:
            arr = self.calib.raw["arrivals"]
            rates = np.asarray(arr["hour_of_week_rate"], dtype=float) * self.arrival_mult
            fams = list(arr["family_mix"].items()); fam_p = np.array([p for _, p in fams]); fam_p /= fam_p.sum()
            vendors = list(arr["attributes"].get("Vendor", {}).items()); v_p = np.array([p for _, p in vendors]); v_p = v_p / v_p.sum() if len(v_p) else v_p
            k = 0
            t = t0 + pd.Timedelta(hours=1)
            while t <= end:
                how = t.dayofweek * 24 + t.hour
                n = self.rng.poisson(rates[how])
                for _ in range(n):
                    fam = fams[self.rng.choice(len(fams), p=fam_p)][0]
                    f = self.calib.family(fam)
                    starts = list(f["start_activities"].items()); s_p = np.array([p for _, p in starts]); s_p /= s_p.sum()
                    act = starts[self.rng.choice(len(starts), p=s_p)][0]
                    its = list(f.get("item_types", {"Standard": 1.0}).items()); i_p = np.array([p for _, p in its]); i_p /= i_p.sum()
                    k += 1
                    self.arrivals.append({"case_id": f"sim_{self.seed}_{k:06d}", "when": t.to_pydatetime(), "activity": act, "family": fam,
                                          "attrs": {"item_type": its[self.rng.choice(len(its), p=i_p)][0], "vendor": vendors[self.rng.choice(len(vendors), p=v_p)][0] if len(vendors) else "", "document_type": "Standard PO"},
                                          "provenance": "exogenous"})
                t += pd.Timedelta(hours=1)

    # ------------------------------------------------------------------ helpers
    def _hour(self, t: datetime) -> datetime:
        return t.replace(minute=0, second=0, microsecond=0)

    def _is_working(self, t: datetime) -> bool:
        return t.weekday() in self.clock.work_days and self.clock.work_hours[0] <= t.hour < self.clock.work_hours[1]

    def _align_working(self, target: datetime, activity: str) -> datetime:
        """Move a human action that lands outside working hours to the next working day, at an hour drawn from the activity's profile."""
        if self._is_working(target):
            return target
        ws, we = self.clock.work_hours
        day = target.replace(hour=0, minute=0, second=0, microsecond=0)
        if target.hour >= we or target.weekday() not in self.clock.work_days:
            day += timedelta(days=1)
        while day.weekday() not in self.clock.work_days:
            day += timedelta(days=1)
        hd = np.asarray(self.calib.activities.get(activity, {}).get("hour_dist") or [1.0] * 24, dtype=float)[ws:we]
        hour = ws + int(self.rng.choice(len(hd), p=hd / hd.sum())) if hd.sum() > 0 else ws
        return day + timedelta(hours=hour)

    def _align_run_day(self, target: datetime, now: datetime, run_days: list[int], activity: str) -> datetime:
        hd = np.asarray(self.calib.activities.get(activity, {}).get("hour_dist") or [1.0] * 24, dtype=float)
        hour = int(np.argmax(hd)) if hd.sum() > 0 else self.clock.work_hours[0]
        for delta in (0, -1, 1, -2, 2, -3, 3, 4, 5, 6):
            cand = (target + timedelta(days=delta)).replace(hour=hour, minute=0, second=0, microsecond=0)
            if cand.weekday() in run_days and cand >= now:
                return cand
        return target

    def _pick_user(self, table: dict[str, tuple[list[str], np.ndarray, set[str]]], activity: str, fallback: str) -> str:
        t = table.get(activity)
        if not t:
            return fallback
        users, cum, _ = t
        return users[min(int(np.searchsorted(cum, self.rng.random())), len(users) - 1)]

    def _pick_executor(self, item: WorkItem, table: dict[str, tuple[list[str], np.ndarray, set[str]]], activity: str, role: str, fallback: str) -> str:
        """Concrete executor: with the calibrated same-user probability the person who did the previous step of this case
        keeps it (same role, and that person performs this activity); otherwise a different user is drawn by share."""
        t = table.get(activity)
        prev = item.state.get("last_agent")
        if self.use_same_user and t and prev and item.state.get("last_role") == role and prev in t[2]:
            if self.rng.random() < self.calib.p_same_user(item.history[-1] if item.history else None, activity, role):
                return prev
            users, cum, _ = t
            for _ in range(4):
                u = users[min(int(np.searchsorted(cum, self.rng.random())), len(users) - 1)]
                if u != prev:
                    return u
            return u
        return self._pick_user(table, activity, fallback)

    def _executor_class(self, activity: str) -> str:
        if activity in self.external_acts:
            return "vendor"
        cs = self.class_override.get(activity) or self.calib.activities.get(activity, {}).get("class_share") or {"human": 1.0}
        keys = ["human", "batch", "system", "vendor"]
        p = np.array([max(0.0, cs.get(k, 0.0)) for k in keys]); p = p / p.sum() if p.sum() > 0 else np.array([1.0, 0, 0, 0])
        return keys[int(self.rng.choice(4, p=p))]

    def _activity_role(self, activity: str) -> str:
        info = self.calib.activities.get(activity)
        if info:
            return info["role"]
        roles = self.act_props.get(activity, {}).get("roles") or ["unknown"]
        return roles[0]

    # ------------------------------------------------------------------ decision (policy chooses among kernel-validated options)
    def _option_weights(self, item: WorkItem, elapsed_h: float = 0.0) -> tuple[list[dict[str, Any]], list[str], str]:
        """Kernel-validated options with normalised weights for the case's next step (no randomness, no side effects)."""
        counts: Counter = item.state["counts"]
        last = item.history[-1]
        fam = item.attributes.get("family", "")
        prev = item.history[-2] if len(item.history) >= 2 else "<START>"
        probs, source = self.calib.next_probs(fam, last, counts, prev=prev, order=self.state_order)
        if self.t0_timing == "joint" and (hit := self._joint_curves(item)):
            probs = {a: float(curve[-1]) for a, curve in hit[0].items() if curve[-1] > 0}
            probs[END] = max(0.0, 1.0 - sum(probs.values()))
            source = "joint_" + hit[1]
        options: list[dict[str, Any]] = []
        rejected: list[str] = []
        for a, p in probs.items():
            if a == END:
                options.append({"kind": "end", "target": END, "weight": float(p)})
                continue
            ok, why = self.constraints.allowed(fam, a, counts)
            if not ok:
                rejected.append(a)
                continue
            w = float(p)
            if elapsed_h > 0:
                w *= self._survival(item, fam, last, a, counts, elapsed_h)
            if a in self.exception_acts and self.exception_mult != 1.0:
                w *= self.exception_mult
            if w > 0:
                options.append({"kind": "do_activity", "target": a, "weight": w})
        if not options or sum(o["weight"] for o in options) <= 0:
            options = [{"kind": "end", "target": END, "weight": 1.0}]
        tot = sum(o["weight"] for o in options)
        for o in options:
            o["weight"] = o["weight"] / tot
        return options, rejected, source

    def _decide(self, item: WorkItem, now: datetime, elapsed_h: float = 0.0) -> None:
        counts: Counter = item.state["counts"]
        last = item.history[-1]
        fam = item.attributes.get("family", "")
        options, rejected, source = self._option_weights(item, elapsed_h)
        self.n_rejected += len(rejected)
        self.n_decisions += 1
        seat = item.state.get("last_role") or self._activity_role(last)
        agent_id = item.state.get("last_agent") or seat
        obs = Observation(agent_id=agent_id, role=seat, sim_time=now.isoformat(),
                          context={"case_id": item.id, "family": fam, "prefix": item.history[-5:], "elapsed_h": round(elapsed_h, 1), "n_events": len(item.history),
                                   "queue_in_role": self.pools[seat].backlog() if seat in self.pools else 0},
                          options=options)
        action: Action = self.registry.for_seat(seat).decide(obs, self.rng)
        valid = {o["target"] for o in options}
        if action.target not in valid:        # kernel rejects an invalid choice and falls back to the weighted draw
            r = self.rng.random() * 1.0; acc = 0.0; choice = options[-1]
            for o in options:
                acc += o["weight"]
                if r <= acc:
                    choice = o; break
            action = Action(kind=choice["kind"], target=choice["target"], params={"fallback": "invalid_choice"})
        dist = {o["target"]: round(o["weight"], 5) for o in options}
        if item.state.get("open_at_t0") and item.id not in self.first_decision:
            self.first_decision[item.id] = dist
        attrs: dict[str, Any] = {"chosen": action.target, "options": dist, "model": source, "elapsed_h": round(elapsed_h, 1)}
        if rejected:
            attrs["rejected"] = rejected
        if action.rationale:
            attrs["rationale"] = action.rationale
        if action.params.get("fallback"):
            attrs["fallback"] = action.params["fallback"]
        self.emit(activity=last, action_type="decide", agent_id=agent_id, role=seat, org_unit=self.role_unit.get(seat, ""), case_id=item.id, attributes=attrs)
        if action.target == END:
            self.ended.add(item.id)
            item.state["ended"] = True
            self.emit(activity=END, action_type="state", agent_id="", role=seat, case_id=item.id, attributes={"reason": "no further step", "n_events": len(item.history)})
            return
        nxt = action.target
        d = self._sample_gap(item, fam, last, nxt, counts, elapsed_h)
        if d is None:                                   # beyond the calibrated support (> 181 d): no step inside any horizon
            self.ended.add(item.id)
            item.state["ended"] = True
            self.emit(activity=END, action_type="state", agent_id="", role=seat, case_id=item.id, attributes={"reason": "next step beyond calibrated horizon", "n_events": len(item.history)})
            return
        remaining = max(0.0, d - elapsed_h) * self.delay_mult[nxt]
        target = item.state["last_ts"] + timedelta(hours=elapsed_h + remaining) if elapsed_h > 0 else now + timedelta(hours=remaining)
        target = max(target, now)
        run_days = self.calib.activities.get(nxt, {}).get("run_days") or []
        if run_days and self._executor_class_is_human_like(nxt):
            target = self._align_run_day(target, now, run_days, nxt)
        if nxt in self.external_acts:
            day = target.replace(hour=0, minute=0, second=0, microsecond=0)
            target = max(day + timedelta(hours=21), now)       # vendor events carry a date, stamped at local midnight
        when = self._hour(target)
        self.scheduler.schedule(when, "ready", case_id=item.id, activity=nxt, ready=when)

    def _joint_curves(self, item: WorkItem):
        """Apply calendar multipliers to cause-specific hazards among cases still
        waiting. Reweighting a completed-event PDF instead would leave the chance
        of an event unchanged even on a large payment run.
        """
        key = (item.id, len(item.history), item.state["last_ts"])
        if self._joint_current[0] == key:
            return self._joint_current[1]
        fam, last, counts = item.attributes.get("family", ""), item.history[-1], item.state["counts"]
        prev = (item.history[-2] if len(item.history) >= 2 else "<START>") if self.state_order >= 2 else None
        hit = self.calib.joint_row(fam, last, counts, prev)
        if not hit:
            return None
        row, level = hit
        curves, grid = row["F"], self.calib.surv_grid
        if self.use_calendar and self.calendar_mode == "hazard":
            base_key = (fam, self.calib.state_key(last, counts), prev)
            if base_key not in self._joint_base_cache:
                grid = np.unique(np.r_[self.calib.surv_grid, self.calib.day_grid_h])
                names = list(curves)
                F = np.array([np.interp(grid, self.calib.surv_grid, curves[a]) for a in names])
                increments = np.maximum(np.diff(F, axis=1, prepend=0), 0)
                survival = np.maximum(1 - np.r_[0, F.sum(axis=0)[:-1]], 1e-12)
                probability = np.clip(increments.sum(axis=0) / survival, 0, 1 - 1e-12)
                hazards = -np.log1p(-probability)[None, :] * increments / np.maximum(increments.sum(axis=0), 1e-12)
                self._joint_base_cache[base_key] = (names, grid, hazards)
            names, grid, hazards = self._joint_base_cache[base_key]
            adjusted = hazards.copy()
            # The interval's midpoint determines its real calendar day.
            mid = (grid + np.r_[0, grid[:-1]]) / 2
            for i, activity in enumerate(names):
                mult = self.calib.calendar_mult(activity, item.state["last_ts"])
                if mult is not None:
                    adjusted[i] *= mult[np.minimum((mid / 24).astype(int), len(mult) - 1)]
            total = adjusted.sum(axis=0)
            survival = np.exp(-np.r_[0, np.cumsum(total)[:-1]])
            increments = survival * -np.expm1(-total) * adjusted / np.maximum(total, 1e-12)
            curves = dict(zip(names, np.cumsum(increments, axis=1)))
        out = (curves, level, grid)
        self._joint_current = (key, out)
        return out

    def _joint_gap(self, item: WorkItem, activity: str):
        hit = self._joint_curves(item)
        curve = hit[0].get(activity) if hit else None
        return (np.asarray(curve) / curve[-1], hit[1], hit[2]) if curve is not None and curve[-1] > 0 else None

    def _survival(self, item: WorkItem, fam: str, last: str, a: str, counts: Counter, elapsed_h: float) -> float:
        """P(gap > elapsed | next = a): from the Aalen-Johansen conditional CDF (t0_timing "aj") or the IPW quantiles;
        for an activity with a payment-run calendar, the gap distribution is reweighted day by day by the calendar."""
        q = self.calib.quantiles(fam, last, a, counts if self.state_timing else None)
        G = self.calib.gap_cdf(fam, last, a, counts) if self.t0_timing == "aj" else None
        if self.t0_timing == "joint":
            G = self._joint_gap(item, a)
        m = self.calib.calendar_mult(a, item.state["last_ts"]) if self.use_calendar and not (self.t0_timing == "joint" and self.calendar_mode == "hazard") else None
        if m is None:
            return float(1.0 - self.calib.gap_cdf_at(G, q, elapsed_h))
        g0, beyond0 = self.calib.day_masses(G, q, 0.0)
        ge, beyonde = self.calib.day_masses(G, q, elapsed_h)
        denom = float(g0 @ m) + beyond0
        return (float(ge @ m) + beyonde) / denom if denom > 0 else 0.0

    def _sample_gap(self, item: WorkItem, fam: str, last: str, nxt: str, counts: Counter, elapsed_h: float) -> float | None:
        """Total gap (hours since the last event) to the chosen next step, conditioned on gap > elapsed_h.
        Calendar activities: draw the day from the calendar-reweighted daily masses, then the hour inside the day.
        Open cases at t0 with t0_timing "aj": invert the Aalen-Johansen conditional CDF. Otherwise: IPW quantiles."""
        q = self.calib.quantiles(fam, last, nxt, counts if self.state_timing else None)
        G = self.calib.gap_cdf(fam, last, nxt, counts) if (self.t0_timing == "aj" and elapsed_h > 0) else None
        if self.t0_timing == "joint":
            G = self._joint_gap(item, nxt)
        m = self.calib.calendar_mult(nxt, item.state["last_ts"]) if self.use_calendar and not (self.t0_timing == "joint" and self.calendar_mode == "hazard") else None
        if m is not None:
            ge, beyond = self.calib.day_masses(G, q, elapsed_h)
            wts = np.append(ge * m, beyond)
            tot = wts.sum()
            if tot <= 0:
                return None
            k = int(self.rng.choice(len(wts), p=wts / tot))
            if k == len(ge):
                return None
            lo = max(self.calib.day_grid_h[k], elapsed_h); hi = self.calib.day_grid_h[k + 1]
            return float(self.rng.uniform(lo, hi))
        if G is not None:
            lo = float(self.calib.gap_cdf_at(G, q, elapsed_h)) if elapsed_h > 0 else 0.0
            if lo >= 1.0:
                return None
            return max(self.calib.invert_gap_cdf(G, self.rng.uniform(lo, 1.0)), elapsed_h)
        return self.calib.sample_delay(self.rng, q, min_h=elapsed_h)

    def _executor_class_is_human_like(self, activity: str) -> bool:
        cs = self.class_override.get(activity) or self.calib.activities.get(activity, {}).get("class_share") or {"human": 1.0}
        return cs.get("human", 0) + cs.get("batch", 0) > 0.5

    # ------------------------------------------------------------------ execution
    def _ready(self, item: WorkItem, activity: str, ready: datetime, now: datetime) -> None:
        cls = self._executor_class(activity)
        if cls == "human":
            role = self._activity_role(activity)
            pool = self.pools.get(role)
            if pool is None:
                pool = self.pools[role] = CapacityPool(role=role, headcount=1.0, actions_per_person_hour=5.0)
            pool.enqueue((item.id, activity, role), self.clock.tick)
            return
        self._execute(item, activity, cls, now, wait_h=0.0, role=self._activity_role(activity) if cls != "vendor" else "vendor")

    def _serve(self, payload: tuple[str, str, str], wait_h: float) -> None:
        case_id, activity, role = payload
        item = self.items[case_id]
        self._execute(item, activity, "human", self.clock.now, wait_h=wait_h, role=role)

    def _execute(self, item: WorkItem, activity: str, cls: str, now: datetime, wait_h: float, role: str) -> None:
        if cls == "human":
            agent_id = self._pick_executor(item, self.activity_users, activity, role, f"{role}_pool")
            pool = self.pools.get(role)
            duration = 1.0 / pool.actions_per_person_hour if pool and pool.actions_per_person_hour > 0 else 0.1
            self.unassisted_work_hours += duration
            assistance = self.assistance.get(activity)
            if assistance:
                self.ai_review_hours += duration * assistance.coverage * assistance.review_overhead
                self.ai_rework_hours += duration * assistance.coverage * assistance.rework_rate * assistance.rework_effort
                duration *= assistance.effort_factor
            self.human_work_hours += duration
            provenance = "simulated"
        elif cls == "batch":
            role = "batch"; agent_id = self._pick_executor(item, self.batch_users, activity, role, "batch"); duration = 0.0; provenance = "simulated"
        elif cls == "system":
            agent_id = "system"; role = "batch"; duration = 0.0; provenance = "simulated"
        else:
            agent_id = ""; role = "vendor"; duration = 0.0; provenance = "exogenous"
        unit = self.role_unit.get(role, "")
        prev_role = item.state.get("last_role")
        if prev_role and prev_role != role and role != "vendor" and prev_role != "vendor":
            self.handoffs += 1
            self.emit(activity=activity, action_type="handoff", agent_id=agent_id, role=role, org_unit=unit, case_id=item.id,
                      attributes={"from_role": prev_role, "to_role": role, "from_agent": item.state.get("last_agent", "")})
        self.emit(activity=activity, action_type="start", agent_id=agent_id, role=role, org_unit=unit, case_id=item.id, wait_h=wait_h, provenance=provenance)
        self.emit(activity=activity, action_type="complete", agent_id=agent_id, role=role, org_unit=unit, case_id=item.id, duration_h=duration, wait_h=wait_h, provenance=provenance,
                  attributes={"executor": cls})
        if cls == "human":
            self.wait_samples.append(wait_h)
        self.sim_events.append((item.id, now, activity, agent_id, role, cls, wait_h))
        item.history.append(activity)
        item.state["counts"][activity] += 1
        item.state["last_ts"] = now
        item.state["last_role"] = role
        item.state["last_agent"] = agent_id if cls in ("human", "batch") else ""
        item.state["open_at_t0"] = item.state.get("open_at_t0", False)
        if activity in self.completing and item.id not in self.completed:
            self.completed[item.id] = now
        if activity in self.constraints.terminal:
            item.closed_at = now
            if item.id not in self.completed:
                self.completed[item.id] = now
            self.emit(activity=activity, action_type="state", agent_id="", role=role, case_id=item.id, attributes={"reason": "terminal"})
            return
        self.steps_this_tick[item.id] += 1
        if self.steps_this_tick[item.id] > 25:        # safety valve against degenerate self-loops inside one hour
            return
        self._decide(item, now)

    def _arrive(self, a: dict[str, Any], now: datetime) -> None:
        item = WorkItem(id=a["case_id"], kind="case", created_at=a["when"], attributes={"family": a["family"], **a["attrs"]},
                        state={"counts": Counter(), "last_ts": now, "last_agent": "", "last_role": "", "open_at_t0": False})
        self.items[item.id] = item
        self.emit(activity=a["activity"], action_type="arrive", agent_id="", role="", case_id=item.id, provenance=a["provenance"],
                  attributes={"family": a["family"], **{k: v for k, v in a["attrs"].items() if v}})
        self._ready(item, a["activity"], now, now)

    # ------------------------------------------------------------------ main loop
    def run(self, writer: RunWriter) -> RunSummary:
        self._writer = writer
        t_start = time.time()
        now = self.clock.now
        # arrivals
        for a in self.arrivals:
            self.scheduler.schedule(self._hour(a["when"]), "arrive", arrival=a)
        # first decision for every live case given the time already elapsed since its last event
        for item in list(self.items.values()):
            elapsed = max(0.0, (now - item.state["last_ts"]) / HOUR)
            self._decide(item, now, elapsed_h=elapsed)
        self.n_arrivals = 0
        for now in self.clock:
            self.steps_this_tick.clear()
            working = self._is_working(now)
            if working:
                for pool in self.pools.values():
                    pool.reset_hour()
            progress = True
            while progress:
                progress = False
                for ev in self.scheduler.due(now):
                    progress = True
                    if ev.kind == "arrive":
                        self.n_arrivals += 1
                        self._arrive(ev.payload["arrival"], now)
                    else:
                        item = self.items.get(ev.payload["case_id"])
                        if item is None or item.closed_at is not None:
                            continue
                        self._ready(item, ev.payload["activity"], ev.payload["ready"], now)
                if working:
                    for pool in self.pools.values():
                        if pool.drain(self.clock.tick, self._serve, self._action_effort if self.assistance else None):
                            progress = True
        self.runtime_s = time.time() - t_start
        return self._summary(writer)

    def _action_effort(self, payload: tuple[str, str, str]) -> float:
        assistance = self.assistance.get(payload[1])
        return assistance.effort_factor if assistance else 1.0

    def _summary(self, writer: RunWriter) -> RunSummary:
        n_cases = len(self.items)
        pop_ids = [cid for cid, it in self.items.items() if not it.state.get("completed_before")]
        completed_ids = [cid for cid in self.completed if cid in self.items and not self.items[cid].state.get("completed_before")]
        cyc = [(self.completed[cid] - self.items[cid].created_at) / HOUR for cid in completed_ids]
        backlog = [cid for cid, it in self.items.items() if it.closed_at is None and cid not in self.ended and cid not in self.completed]
        queued = sum(p.backlog() for p in self.pools.values())
        exc_cases = {e[0] for e in self.sim_events if e[2] in self.exception_acts}
        active_cases = {e[0] for e in self.sim_events}
        act_counts = Counter(e[2] for e in self.sim_events)
        waits = np.asarray(self.wait_samples) if self.wait_samples else np.zeros(1)
        util = {r: round(p.mean_utilization(), 4) for r, p in self.pools.items()}
        headline = {
            "t0": self.t0.isoformat(), "horizon_days": self.horizon_days, "track": self.track,
            "open_cases_at_t0": int(self.n_open_at_t0), "cases_considered_at_t0": int(self.n_considered_at_t0),
            "arrivals": int(self.n_arrivals), "events": int(len(self.sim_events)), "trace_rows": int(self._n_events),
            "cases_with_activity": int(len(active_cases)),
            "completed_cases": int(len(completed_ids)),
            "completion_rate_14d": round(100.0 * len(completed_ids) / len(pop_ids), 2) if pop_ids else 0.0,
            "median_cycle_hours_completed": round(float(np.median(cyc)), 1) if cyc else None,
            "p90_cycle_hours": round(float(np.quantile(cyc, 0.9)), 1) if cyc else None,
            "backlog_end": int(len(backlog)), "queued_actions_end": int(queued), "ended_cases": int(len(self.ended)),
            "exceptions": int(len(exc_cases)), "exception_rate": round(100.0 * len(exc_cases) / len(pop_ids), 2) if pop_ids else 0.0,
            "handoffs": int(self.handoffs), "handoffs_per_case": round(self.handoffs / len(active_cases), 3) if active_cases else 0.0,
            "mean_wait_h": round(float(waits.mean()), 2), "p90_wait_h": round(float(np.quantile(waits, 0.9)), 2),
            "decisions": int(self.n_decisions), "options_rejected_by_constraints": int(self.n_rejected),
            "utilization": util, "workforce": self.workforce, "activity_counts": dict(act_counts.most_common(15)),
            "runtime_s": round(self.runtime_s, 1), "policies": self.registry.describe(),
            "workload": {"human_hours": self.human_work_hours, "unassisted_hours": self.unassisted_work_hours,
                         "review_hours": self.ai_review_hours, "rework_hours": self.ai_rework_hours},
            "model": {"state_order": self.state_order, "state_timing": self.state_timing, "t0_timing": self.t0_timing, "calendar": self.use_calendar, "calendar_mode": self.calendar_mode, "same_user": self.use_same_user},
        }
        return RunSummary(run_id=writer.run_id, instance=self.ctx.id, scenario=self.scenario.get("id", "baseline"), seed=self.seed,
                          start=self.clock.start.isoformat(), end=self.clock.end.isoformat(), ticks=self.clock.tick, events=self._n_events, headline=headline)


# --------------------------------------------------------------------------- evaluation
def _window_metrics_actual(ev: pd.DataFrame, cases: pd.DataFrame, t0: pd.Timestamp, H: int, pop: set[str], completing: set[str], terminal: set[str],
                           exceptions: set[str]) -> dict[str, Any]:
    end = t0 + pd.Timedelta(days=H)
    w = ev[(ev.ts > t0) & (ev.ts <= end)]
    return _window_metrics(w.rename(columns={"ts": "when", "resource": "agent"}), cases, t0, H, pop, completing, terminal, exceptions)


def _window_metrics(w: pd.DataFrame, cases: pd.DataFrame, t0: pd.Timestamp, H: int, pop: set[str], completing: set[str], terminal: set[str], exceptions: set[str]) -> dict[str, Any]:
    """w: events inside (t0, t0+H] with columns case_id, activity, when, agent, resource_class (sorted by case, time)."""
    w = w[w.case_id.isin(pop) & (w.when > t0) & (w.when <= t0 + pd.Timedelta(days=H))].sort_values(["case_id", "when"])
    in_pop = w[w.case_id.isin(pop)]
    comp = in_pop[in_pop.activity.isin(completing | terminal)].groupby("case_id").when.min()
    first_ts = cases.set_index("case_id").first_ts
    cyc = ((comp - first_ts.reindex(comp.index)) / pd.Timedelta(hours=1)).dropna()
    exc = in_pop[in_pop.activity.isin(exceptions)].case_id.nunique()
    hb = w[~w.resource_class.isin(["vendor", "system"])]
    ho = int((hb.case_id.eq(hb.case_id.shift(1)) & hb.agent.ne(hb.agent.shift(1))).sum())
    active = w.case_id.nunique()
    same = w.case_id.eq(w.case_id.shift(-1))
    pairs = pd.DataFrame({"from": w.activity[same].values, "to": w.activity.shift(-1)[same].values, "gap": ((w.when.shift(-1)[same].values - w.when[same].values) / np.timedelta64(1, "h"))})
    p50 = pairs.groupby(["from", "to"]).gap.agg(["median", "size"])
    days = ((comp - t0) / pd.Timedelta(days=1)).apply(math.ceil).clip(lower=1)
    curve = [int((days <= d).sum()) for d in range(1, H + 1)]
    weeks = ((w.when - t0) / pd.Timedelta(days=7)).apply(math.floor).clip(lower=0)
    return {"population": len(pop), "completed": int(len(comp)), "completion_rate": 100.0 * len(comp) / len(pop) if pop else float("nan"),
            "median_cycle_h": float(cyc.median()) if len(cyc) else float("nan"), "p90_cycle_h": float(cyc.quantile(0.9)) if len(cyc) else float("nan"),
            "exception_cases": int(exc), "exception_rate": 100.0 * exc / len(pop) if pop else float("nan"),
            "handoffs": ho, "handoffs_per_active_case": ho / active if active else float("nan"), "events": int(len(w)), "active_cases": int(active),
            "activity_counts": Counter(w.activity.value_counts().to_dict()), "transition_p50": {f"{a}|{b}": float(m) for (a, b), m in p50["median"].items()},
            "transition_n": {f"{a}|{b}": int(n) for (a, b), n in p50["size"].items()}, "completion_curve": curve,
            "weekly_events": [int((weeks == k).sum()) for k in range(max(1, math.ceil(H / 7)))]}


def _first_actual_next(ev: pd.DataFrame, t0: pd.Timestamp, case_ids: set[str]) -> pd.Series:
    post = ev[(ev.ts > t0) & ev.case_id.isin(case_ids)]
    return post.groupby("case_id").activity.first()


def _mean(xs: list[float]) -> float:
    xs = [x for x in xs if x is not None and not (isinstance(x, float) and math.isnan(x))]
    return float(np.mean(xs)) if xs else float("nan")


def _run_world(ctx: InstanceContext, scenario: dict[str, Any], seed: int, t0: str | None = None) -> tuple[World, RunSummary]:
    sc = json.loads(json.dumps(scenario))
    if t0:
        sc.setdefault("world", {})["t0"] = t0
    writer = RunWriter(ctx.id, sc["id"], config={"instance": ctx.id, "scenario": sc, "seed": seed, "evaluation": True})
    world = World.from_instance(ctx, sc, seed)
    summary = world.run(writer)
    writer.close(summary.to_json())
    print(f"[{ctx.id}] eval run {sc['id']} t0={sc.get('world', {}).get('t0')} seed={seed} -> {writer.run_id} ({summary.events} rows, {world.runtime_s:.1f}s)", flush=True)
    return world, summary


def fit_markov_baselines(ev: pd.DataFrame, cases: pd.DataFrame, calib: dict[str, Any]) -> tuple[MarkovNextActivity, MarkovNextActivity]:
    """Prefix Markov order 1 and 2 fitted on the training window only (cases created in it, events inside it)."""
    fit = calib["fitted_on"]
    tr_start = pd.Timestamp(fit["cases_created"].split("..")[0].strip()); tr_end = pd.Timestamp(fit["events_until"]) + pd.Timedelta(days=1)
    tr_cases = set(cases[(cases.first_ts >= tr_start) & (cases.first_ts < tr_end)].case_id)
    tr = ev[ev.case_id.isin(tr_cases) & (ev.ts < tr_end)]
    traces = tr.groupby("case_id", sort=False).activity.agg(list).tolist()
    return MarkovNextActivity(order=1, end_token=END).fit(traces), MarkovNextActivity(order=2, end_token=END).fit(traces)


def _renorm(d: dict[str, float]) -> dict[str, float]:
    d = {a: p for a, p in d.items() if a != END}; s = sum(d.values())
    return {a: p / s for a, p in d.items()} if s > 0 else d


def score_run(ev: pd.DataFrame, cases: pd.DataFrame, world: "World", summ: RunSummary, t0: pd.Timestamp, H: int, mk1: MarkovNextActivity, mk2: MarkovNextActivity,
              completing: set[str], terminal: set[str], exceptions: set[str], top_k: int, truth_next: pd.Series | None = None) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Score one finished world against the held-out truth. Returns (row, sim_metrics, act_metrics); the scorer is the only
    place that reads events after t0."""
    pop = {cid for cid, it in world.items.items() if not it.state.get("completed_before")}
    if truth_next is None:
        truth_next = _first_actual_next(ev, t0, set(world.first_decision))
    act = _window_metrics_actual(ev, cases, t0, H, pop, completing, terminal, exceptions)
    if world.sim_events:
        sw = pd.DataFrame(world.sim_events, columns=["case_id", "when", "activity", "agent", "role", "resource_class", "wait_h"])
        sw["when"] = pd.to_datetime(sw["when"])
    else:
        sw = pd.DataFrame(columns=["case_id", "when", "activity", "agent", "role", "resource_class", "wait_h"])
    sim = _window_metrics(sw, cases, t0, H, pop, completing, terminal, exceptions)
    summ.headline.update({"events": sim["events"], "exception_rate": sim["exception_rate"],
                          "handoffs_per_case": sim["handoffs_per_active_case"], "weekly_events": sim["weekly_events"],
                          "completion_curve": [100 * n / max(1, len(pop)) for n in sim["completion_curve"]]})
    (world.ctx.runs_dir / world.scenario["id"] / summ.run_id / "summary.json").write_text(json.dumps(summ.to_json(), default=_json_default))
    # next-activity scoring on cases that really have a next event
    ids = [cid for cid in truth_next.index if cid in world.first_decision and not world.items[cid].state.get("completed_before")]
    truth = [truth_next[cid] for cid in ids]
    eng = [_renorm(world.first_decision[cid]) for cid in ids]
    prefixes = {cid: world.items[cid].history[: world.items[cid].attributes.get("replayed_prefix", len(world.items[cid].history))] for cid in ids}
    m1 = [_renorm(mk1.probs(prefixes[cid])) for cid in ids]
    m2 = [_renorm(mk2.probs(prefixes[cid])) for cid in ids]
    argmax = lambda d: max(d, key=d.get) if d else None  # noqa: E731
    # sampled-path accuracy: what the simulation actually did first for the case
    first_sim = sw.sort_values("when").groupby("case_id").activity.first() if len(sw) else pd.Series(dtype=str)
    both = [(first_sim[cid], t) for cid, t in zip(ids, truth) if cid in first_sim.index]
    sampled_acc = accuracy([a for a, _ in both], [t for _, t in both])
    tp_keys = sorted(act["transition_n"], key=act["transition_n"].get, reverse=True)[:top_k]
    rc = rank_correlation([sim["transition_p50"].get(k, float("nan")) for k in tp_keys], [act["transition_p50"][k] for k in tp_keys]) if all(k in sim["transition_p50"] for k in tp_keys) else float("nan")
    row = {"t0": t0.strftime("%Y-%m-%d"), "seed": world.seed, "run_id": summ.run_id, "runtime_s": world.runtime_s, "scored_cases": len(ids),
           "next_acc": accuracy([argmax(d) for d in eng], truth), "next_logloss": log_loss(eng, truth), "next_acc_sampled": sampled_acc,
           "markov1_acc": accuracy([argmax(d) for d in m1], truth), "markov1_logloss": log_loss(m1, truth),
           "markov2_acc": accuracy([argmax(d) for d in m2], truth), "markov2_logloss": log_loss(m2, truth),
           "sim": {k: v for k, v in sim.items() if k not in ("activity_counts", "transition_p50", "transition_n")},
           "act": {k: v for k, v in act.items() if k not in ("activity_counts", "transition_p50", "transition_n")},
           "jsd_activity": jensen_shannon(sim["activity_counts"], act["activity_counts"]), "p50_rank_corr": rc, "top_keys": tp_keys,
           "headline": summ.headline}
    return row, sim, act


@lru_cache(maxsize=2)
def _scoring_context(instance_id: str, calibration_mtime: float):
    from ..instances import get_instance
    ctx = get_instance(instance_id)
    ev, cases = load_events(ctx)
    calib = json.loads((ctx.calibration_dir / "process.json").read_text())
    props = {a["id"]: a.get("properties", {}) for a in ctx.yaml("ontology/bindings.yaml")["activities"]}
    cons = Constraints(ctx.yaml("calibration/constraints.yaml"), props)
    completing = {a for a, p in props.items() if p.get("completes_case")}
    return ctx, ev, cases, cons, completing, set(calib.get("exceptions", {}).get("core", [])), fit_markov_baselines(ev, cases, calib)


def _forecast_job(job):
    iid, mtime, scenario, cutoff, seed, horizon, top_k, score = job
    ctx, ev, cases, cons, completing, exceptions, models = _scoring_context(iid, mtime)
    world, summary = _run_world(ctx, scenario, seed, t0=cutoff)
    if score:
        return score_run(ev, cases, world, summary, pd.Timestamp(cutoff), horizon, *models, completing, cons.terminal, exceptions, top_k)
    pop = {cid for cid, it in world.items.items() if not it.state.get("completed_before")}
    rows = pd.DataFrame(world.sim_events, columns=["case_id", "when", "activity", "agent", "role", "resource_class", "wait_h"])
    sm = _window_metrics(rows, cases, pd.Timestamp(cutoff), horizon, pop, completing, cons.terminal, exceptions)
    summary.headline.update({"events": sm["events"], "exception_rate": sm["exception_rate"], "handoffs_per_case": sm["handoffs_per_active_case"],
                             "weekly_events": sm["weekly_events"], "completion_curve": [100 * n / max(1, len(pop)) for n in sm["completion_curve"]]})
    (ctx.runs_dir / scenario["id"] / summary.run_id / "summary.json").write_text(json.dumps(summary.to_json(), default=_json_default))
    return summary.run_id, summary.headline


def _forecast_jobs(ctx, scenario, cutoffs, seeds, horizon, top_k, workers, score=True):
    mtime = (ctx.calibration_dir / "process.json").stat().st_mtime
    jobs = [(ctx.id, mtime, scenario, c, sd, horizon, top_k, score) for c in cutoffs for sd in seeds]
    if workers <= 1:
        yield from map(_forecast_job, jobs)
    else:
        with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn")) as executor:
            # map preserves protocol order, independent of worker completion order.
            yield from executor.map(_forecast_job, jobs)


def evaluate(ctx: InstanceContext, scenario_ids: list[str]) -> dict[str, Any]:
    proto = ctx.yaml("evaluation/protocol.yaml")
    cutoffs = [str(c) for c in proto.get("cutoffs", ["2018-09-03"])]
    H = int(proto.get("horizon_days", 14))
    seeds = [int(s) for s in proto.get("seeds", [1])]
    top_k = int(proto.get("top_transitions", 10))
    base_id = proto.get("baseline_scenario", "baseline")
    ev, cases = load_events(ctx)
    calib = json.loads((ctx.calibration_dir / "process.json").read_text())
    bindings = ctx.yaml("ontology/bindings.yaml")
    act_props = {a["id"]: (a.get("properties") or {}) for a in bindings.get("activities", [])}
    cons = Constraints(ctx.yaml("calibration/constraints.yaml"), act_props)
    completing = {a for a, p in act_props.items() if p.get("completes_case")}
    exceptions = set(calib.get("exceptions", {}).get("core", []))
    base = load_scenario(ctx, base_id)
    workers = max(1, int(proto.get("workers", 1)))

    # ---- baselines: Markov next-activity models fitted on the training window only
    mk1, mk2 = fit_markov_baselines(ev, cases, calib)

    # ---- historical baseline rates at training-window cutoffs (same population rule, same metrics)
    hist = []
    for c in calib.get("historical_cutoffs", []):
        t0 = pd.Timestamp(c)
        pre = open_cases_at(ev, cases, t0, cons.dormancy_days, cons.terminal, completing)
        pop = set(pre[~pre.completed_before].case_id) | set(cases[(cases.first_ts > t0) & (cases.first_ts <= t0 + pd.Timedelta(days=H))].case_id)
        hist.append(_window_metrics_actual(ev, cases, t0, H, pop, completing, cons.terminal, exceptions))
    hist_rate = lambda k: _mean([h[k] for h in hist])  # noqa: E731

    # ---- C-I evaluation runs: baseline world at each cutoff x seed
    per_run: list[dict[str, Any]] = []
    act_sim_total: Counter = Counter(); act_act_total: Counter = Counter()
    curve_sim = np.zeros(H); curve_act = np.zeros(H); n_curve = 0
    p50_sim_acc: dict[str, list[float]] = defaultdict(list); p50_act_acc: dict[str, list[float]] = defaultdict(list)
    tn_sim: Counter = Counter(); tn_act: Counter = Counter(); p50_sim_all: dict[str, list[float]] = defaultdict(list); p50_act_all: dict[str, list[float]] = defaultdict(list)
    for row, sim, act in _forecast_jobs(ctx, base, cutoffs, seeds, H, top_k, workers):
        pop_n = row["sim"]["population"]
        for k in row.pop("top_keys"):
            if k in sim["transition_p50"]:
                p50_sim_acc[k].append(sim["transition_p50"][k]); p50_act_acc[k].append(act["transition_p50"][k])
        tn_sim.update(sim["transition_n"]); tn_act.update(act["transition_n"])
        for k, v in sim["transition_p50"].items():
            p50_sim_all[k].append(v)
        for k, v in act["transition_p50"].items():
            p50_act_all[k].append(v)
        per_run.append(row)
        act_sim_total.update(sim["activity_counts"]); act_act_total.update(act["activity_counts"])
        curve_sim += np.array(sim["completion_curve"]) / max(1, pop_n) * 100; curve_act += np.array(act["completion_curve"]) / max(1, pop_n) * 100; n_curve += 1
    n_runs = len(per_run)

    # ---- observed before period: reference data only, no simulated before
    before_cutoffs = [str(c) for c in proto.get("before_cutoffs", [])]
    if proto.get("change_date") and any(pd.Timestamp(c) + pd.Timedelta(days=H) > pd.Timestamp(proto["change_date"]) for c in before_cutoffs):
        raise ValueError("Before-policy reference horizons must end before the change")
    before_runs: list[dict[str, Any]] = []
    for c in before_cutoffs:
        t0 = pd.Timestamp(c)
        pre = open_cases_at(ev, cases, t0, cons.dormancy_days, cons.terminal, completing)
        arrivals = cases[(cases.first_ts > t0) & (cases.first_ts <= t0 + pd.Timedelta(days=H))]
        pop = set(pre[~pre.completed_before].case_id) | set(arrivals.case_id)
        actual = _window_metrics_actual(ev, cases, t0, H, pop, completing, cons.terminal, exceptions)
        staff = ev[(ev.ts >= t0 - pd.Timedelta(days=14)) & (ev.ts < t0) & (ev.resource_class == "human")].resource.nunique()
        before_runs.append({"act": actual, "staff": staff, "arrivals": len(arrivals)})

    def period_block(rows: list[dict[str, Any]], cuts: list[str]) -> dict[str, Any]:
        if not rows:
            return {"cutoffs": cuts, "runs": 0, "metrics": {}}
        def pm(key_sim: str, key_act: str | None, scale: float = 1.0, nd: int = 3) -> dict[str, Any]:
            sv = [(r[key_sim] if key_sim in r else r["sim"][key_sim]) * scale for r in rows]
            out = {"simulated": round(_mean(sv), nd), "interval": [round(v, nd) for v in interval(sv)]}
            if key_act:
                out["actual"] = round(_mean([r["act"][key_act] * scale for r in rows]), nd)
            return out
        staff = [sum(v.get("active_headcount", 0) for v in (r["headline"].get("workforce") or {}).values()) for r in rows]
        return {"cutoffs": cuts, "runs": len(rows),
                "staff_active": round(_mean(staff), 1), "arrivals": round(_mean([r["headline"].get("arrivals", 0) for r in rows]), 0), "population": round(_mean([r["sim"]["population"] for r in rows]), 0),
                "metrics": {"next_activity_accuracy": pm("next_acc", None, 100, 2), "completion_14d": pm("completion_rate", "completion_rate", 1, 3),
                            "median_cycle_hours": pm("median_cycle_h", "median_cycle_h", 1, 1), "exception_rate": pm("exception_rate", "exception_rate", 1, 3),
                            "handoffs_per_case": pm("handoffs_per_active_case", "handoffs_per_active_case", 1, 3),
                            "events_per_week": {"simulated": round(_mean([np.mean(r["sim"]["weekly_events"]) for r in rows]), 0), "actual": round(_mean([np.mean(r["act"]["weekly_events"]) for r in rows]), 0),
                                                "interval": [round(v, 0) for v in interval([np.mean(r["sim"]["weekly_events"]) for r in rows])]}}}
    before_metrics = {mid: {"actual": _mean([r["act"][key] for r in before_runs])} for mid, key in
                      (("completion_14d", "completion_rate"), ("median_cycle_hours", "median_cycle_h"),
                       ("exception_rate", "exception_rate"), ("handoffs_per_case", "handoffs_per_active_case"))}
    before_metrics["events_per_week"] = {"actual": _mean([np.mean(r["act"]["weekly_events"]) for r in before_runs])}
    periods = {"before": {"cutoffs": before_cutoffs, "runs": 0, "observations": len(before_runs), "metrics": before_metrics,
                          "staff_active": _mean([r["staff"] for r in before_runs]), "arrivals": _mean([r["arrivals"] for r in before_runs])},
               "after": period_block(per_run, cutoffs)}
    change = dict(proto.get("change") or {})
    if before_runs and per_run:
        change.update({"staff_before": periods["before"]["staff_active"], "staff_after": periods["after"]["staff_active"],
                       "ratio": round(periods["after"]["staff_active"] / max(1.0, periods["before"]["staff_active"]), 3)})

    # Compare errors per prediction window, so errors in opposite directions cannot
    # disappear when averaged. All comparator inputs precede the scored window.
    business_validation = []
    for mid, key in (("completion_14d", "completion_rate"), ("median_cycle_hours", "median_cycle_h"),
                     ("exception_rate", "exception_rate"), ("handoffs_per_case", "handoffs_per_active_case"),
                     ("events_per_week", "weekly_events")):
        value = lambda row: float(np.mean(row[key])) if key == "weekly_events" else float(row[key])
        prior_value = before_metrics[mid]["actual"]
        history = _mean([value(h) for h in hist])
        windows = []
        for c in cutoffs:
            rows = [r for r in per_run if r["t0"] == c]
            actual = value(rows[0]["act"])
            predicted = _mean([value(r["sim"]) for r in rows])
            staff = sum(v["active_headcount"] for v in rows[0]["headline"]["workforce"].values())
            ratio = staff / max(1, periods["before"]["staff_active"])
            scaled = prior_value * ratio if mid in ("completion_14d", "events_per_week") else prior_value / ratio if mid == "median_cycle_hours" else prior_value
            windows.append({"cutoff": c, "actual": actual, "simulated": predicted,
                            "baselines": {"carry_forward": prior_value, "training_average": history, "scale_with_staff": scaled}})
        engine_mae = _mean([abs(w["simulated"] - w["actual"]) for w in windows])
        baseline_mae = {name: _mean([abs(w["baselines"][name] - w["actual"]) for w in windows]) for name in windows[0]["baselines"]}
        best = min(baseline_mae, key=baseline_mae.get)
        business_validation.append({"id": mid, "windows": windows, "simulation_mae": engine_mae,
                                    "baseline_mae": baseline_mae, "best_baseline": best,
                                    "beats_best_baseline": engine_mae < baseline_mae[best],
                                    "error_reduction_pct": 100 * (1 - engine_mae / baseline_mae[best]) if baseline_mae[best] > 0 else None})

    def agg(key_sim: str, key_act: str | None = None, hist_key: str | None = None, scale: float = 1.0) -> dict[str, Any]:
        s = [r[key_sim] if key_sim in r else r["sim"][key_sim] for r in per_run]
        out: dict[str, Any] = {"simulated": _mean(s) * scale, "interval": [v * scale for v in interval(s)]}
        if key_act:
            out["actual"] = _mean([r["act"][key_act] for r in per_run]) * scale
        if hist_key:
            out["baseline"] = hist_rate(hist_key) * scale
        return out

    best_mk_acc = max(_mean([r["markov1_acc"] for r in per_run]), _mean([r["markov2_acc"] for r in per_run]))
    best_mk_ll = min(_mean([r["markov1_logloss"] for r in per_run]), _mean([r["markov2_logloss"] for r in per_run]))
    metrics = [
        {"id": "next_activity_accuracy", "label": "Next-step accuracy on open cases (top-1)", "unit": "%", "better": "higher", **agg("next_acc", scale=100), "actual": None, "baseline": best_mk_acc * 100,
         "baseline_label": "best prefix Markov model (order 1/2)", "note": f"Markov order 1: {_mean([r['markov1_acc'] for r in per_run])*100:.1f}%, order 2: {_mean([r['markov2_acc'] for r in per_run])*100:.1f}%; for cases where the simulation took a step inside the horizon, the sampled step itself equalled the real next step {_mean([r['next_acc_sampled'] for r in per_run])*100:.1f}% of the time"},
        {"id": "next_activity_logloss", "label": "Next-step log-loss on open cases", "unit": "nats", "better": "lower", **agg("next_logloss"), "actual": None, "baseline": best_mk_ll, "baseline_label": "best prefix Markov model"},
        {"id": "completion_14d", "label": f"Cases completed within {H} days", "unit": "%", "better": "closer", **agg("completion_rate", "completion_rate", "completion_rate"), "baseline_label": "training-window historical rate"},
        {"id": "median_cycle_hours", "label": "Median cycle time of completed cases", "unit": "h", "better": "closer", **agg("median_cycle_h", "median_cycle_h", "median_cycle_h"), "baseline_label": "training-window historical"},
        {"id": "exception_rate", "label": "Cases with at least one exception", "unit": "%", "better": "closer", **agg("exception_rate", "exception_rate", "exception_rate"), "baseline_label": "training-window historical rate"},
        {"id": "handoffs_per_case", "label": "Hand-offs per active case", "unit": "", "better": "closer", **agg("handoffs_per_active_case", "handoffs_per_active_case", "handoffs_per_active_case"), "baseline_label": "training-window historical"},
        {"id": "activity_volume_jsd", "label": "Activity-mix divergence, simulated vs actual (Jensen-Shannon)", "unit": "bits", "better": "lower", **agg("jsd_activity"), "actual": None, "baseline": None},
        {"id": "events_per_week", "label": "Events per week in the horizon", "unit": "", "better": "closer", "simulated": _mean([np.mean(r["sim"]["weekly_events"]) for r in per_run]), "actual": _mean([np.mean(r["act"]["weekly_events"]) for r in per_run]),
         "baseline": _mean([np.mean(h["weekly_events"]) for h in hist]), "interval": list(interval([np.mean(r["sim"]["weekly_events"]) for r in per_run])), "baseline_label": "training-window historical"},
        {"id": "transition_p50_rank_corr", "label": f"Rank correlation of median delays, top {top_k} transitions", "unit": "", "better": "higher", **agg("p50_rank_corr"), "actual": None, "baseline": None},
    ]
    for m in metrics:
        m.setdefault("actual", None); m.setdefault("baseline", None)
    headline = {m["id"]: {k: m.get(k) for k in ("label", "simulated", "actual", "baseline", "unit", "better")} for m in metrics
                if m["id"] in ("next_activity_accuracy", "completion_14d", "exception_rate", "handoffs_per_case", "median_cycle_hours", "events_per_week")}

    # ---- scenario comparison on the exact same cutoffs and seeds
    scen_rows: list[dict[str, Any]] = []
    scen_titles: dict[str, str] = {}
    others = [s for s in scenario_ids if s != base_id]
    kpis = ["completed_cases", "completion_rate_14d", "median_cycle_hours_completed", "p90_cycle_hours", "backlog_end", "queued_actions_end", "exceptions", "mean_wait_h", "p90_wait_h", "events", "arrivals"]
    def kpi_row(sid: str, title: str, heads: list[dict]) -> dict[str, Any]:
        row: dict[str, Any] = {"scenario": sid, "title": title, "seeds": len(heads)}
        for k in kpis:
            row[k] = _mean([h.get(k) for h in heads])
        for r in ("ap_invoice", "ap_payment", "goods_receipt", "purchasing_clerk", "buyer"):
            row[f"util_{r}"] = _mean([h["utilization"].get(r) for h in heads if h.get("utilization")]) * 100
        return row
    base_heads = [r["headline"] for r in per_run]
    run_ids = {base_id: [r["run_id"] for r in per_run]}
    scen_rows.append(kpi_row(base_id, base.get("title", base_id), base_heads))
    for sid in others:
        sc = load_scenario(ctx, sid)
        scen_titles[sid] = sc.get("title", sid)
        heads = []
        run_ids[sid] = []
        for run_id, run_headline in _forecast_jobs(ctx, sc, cutoffs, seeds, H, top_k, workers, score=False):
            heads.append(run_headline)
            run_ids[sid].append(run_id)
        scen_rows.append(kpi_row(sid, sc.get("title", sid), heads))

    # ---- charts
    top_acts = [a for a, _ in (act_act_total + act_sim_total).most_common(15)]
    tp_keys = sorted(p50_act_acc, key=lambda k: len(p50_act_acc[k]), reverse=True)[:top_k]
    charts = [
        {"id": "activity_volumes", "type": "hbar", "title": f"Events per activity in the {H}-day horizon (mean per cutoff)", "x_label": "events", "y_label": "",
         "x": top_acts, "series": [{"name": "Simulation prediction", "y": [round(act_sim_total[a] / n_runs, 1) for a in top_acts]}, {"name": "Actual outcome", "y": [round(act_act_total[a] / n_runs, 1) for a in top_acts]}],
         "note": f"Averaged over {len(cutoffs)} cutoffs x {len(seeds)} seeds; actual counts are the held-out events of the same cases."},
        {"id": "completion_curve", "type": "line", "title": "Share of live cases completed by day", "x_label": "days after t0", "y_label": "% of live cases",
         "x": list(range(1, H + 1)), "series": [{"name": "Simulation prediction", "y": [round(v, 2) for v in (curve_sim / max(1, n_curve))]}, {"name": "Actual outcome", "y": [round(v, 2) for v in (curve_act / max(1, n_curve))]}], "note": "Completion = Clear Invoice or Delete PO Item."},
        {"id": "transition_p50", "type": "hbar", "title": "Median delay of the busiest transitions inside the horizon (hours)", "x_label": "hours", "y_label": "",
         "x": [k.replace("|", " -> ") for k in tp_keys], "series": [{"name": "Simulation prediction", "y": [round(_mean(p50_sim_acc[k]), 1) for k in tp_keys]}, {"name": "Actual outcome", "y": [round(_mean(p50_act_acc[k]), 1) for k in tp_keys]}], "note": "Both sides are censored by the 14-day horizon in the same way."},
        {"id": "next_activity", "type": "bar", "title": "Next-step prediction on open cases", "x_label": "", "y_label": "% correct",
         "x": ["Simulation (constraints + state + elapsed time)", "Markov order 1", "Markov order 2"], "series": [{"name": "Top-1 accuracy", "y": [round(_mean([r["next_acc"] for r in per_run]) * 100, 2), round(_mean([r["markov1_acc"] for r in per_run]) * 100, 2), round(_mean([r["markov2_acc"] for r in per_run]) * 100, 2)]}], "note": f"{int(_mean([r['scored_cases'] for r in per_run]))} open cases scored per cutoff."},
        {"id": "weekly_throughput", "type": "bar", "title": "Events per week in the horizon", "x_label": "week", "y_label": "events",
         "x": [f"week {i+1}" for i in range(max(1, math.ceil(H / 7)))], "series": [{"name": "Simulation prediction", "y": [round(_mean([r["sim"]["weekly_events"][i] for r in per_run]), 0) for i in range(max(1, math.ceil(H / 7)))]}, {"name": "Actual outcome", "y": [round(_mean([r["act"]["weekly_events"][i] for r in per_run]), 0) for i in range(max(1, math.ceil(H / 7)))]}], "note": ""},
        {"id": "scenario_completed", "type": "bar", "title": f"Cases completed in {H} days by scenario (all prediction cutoffs)", "x_label": "", "y_label": "cases",
         "x": [r["title"] for r in scen_rows], "series": [{"name": "Completed cases", "y": [round(r["completed_cases"], 0) for r in scen_rows]}], "note": "Mean over seeds."},
        {"id": "scenario_cycle", "type": "bar", "title": "Median and p90 cycle time of completed cases by scenario (hours)", "x_label": "", "y_label": "hours",
         "x": [r["title"] for r in scen_rows], "series": [{"name": "Median", "y": [round(r["median_cycle_hours_completed"] or 0, 0) for r in scen_rows]}, {"name": "p90", "y": [round(r["p90_cycle_hours"] or 0, 0) for r in scen_rows]}], "note": ""},
        {"id": "scenario_backlog", "type": "bar", "title": "Open cases and queued actions at the end of the horizon by scenario", "x_label": "", "y_label": "count",
         "x": [r["title"] for r in scen_rows], "series": [{"name": "Open cases", "y": [round(r["backlog_end"], 0) for r in scen_rows]}, {"name": "Queued actions", "y": [round(r["queued_actions_end"], 0) for r in scen_rows]}], "note": ""},
        {"id": "scenario_utilization", "type": "bar", "title": "Utilization of accounts-payable roles by scenario (% of working-hour capacity)", "x_label": "", "y_label": "%",
         "x": [r["title"] for r in scen_rows], "series": [{"name": "AP invoice clerks", "y": [round(r["util_ap_invoice"], 1) for r in scen_rows]}, {"name": "AP payment specialists", "y": [round(r["util_ap_payment"], 1) for r in scen_rows]}], "note": ""},
    ]
    # process map (actual full log from ingest + simulated horizon) for the instance's process-map plugin page
    pm_path = ctx.data_normalized / "process_map.json"
    pm = json.loads(pm_path.read_text()) if pm_path.exists() else {"actual": None}
    def pm_edges(tn: Counter, p50: dict[str, list[float]], min_n: int) -> list[dict]:
        return [{"from": k.split("|")[0], "to": k.split("|")[1], "n": round(n / n_runs, 1), "p50_h": round(_mean(p50.get(k, [])), 1)} for k, n in tn.most_common() if n / n_runs >= min_n]
    pm["simulated"] = {"note": f"mean per {H}-day horizon over {n_runs} baseline evaluation runs ({len(cutoffs)} cutoffs x {len(seeds)} seeds)",
                       "nodes": [{"id": a, "events": round(n / n_runs, 1)} for a, n in act_sim_total.most_common()], "edges": pm_edges(tn_sim, p50_sim_all, 2)}
    pm["actual_window"] = {"note": f"actual events of the same cases in the same {H}-day horizons (mean per cutoff)",
                           "nodes": [{"id": a, "events": round(n / n_runs, 1)} for a, n in act_act_total.most_common()], "edges": pm_edges(tn_act, p50_act_all, 2)}
    pm_path.write_text(json.dumps(pm, indent=1))

    out = ctx.runs_dir / "evaluation.json"
    model_flags = per_run[0]["headline"].get("model", {}) if per_run else {}
    result = {"instance": ctx.id, "generated": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"), "scenarios": [base_id] + others,
              "calibration_sha256": calib.get("sha256"), "calibration_window": calib.get("fitted_on"), "model": model_flags, "run_ids": run_ids,
              "protocol": {"cutoffs": cutoffs, "horizon_days": H, "seeds": seeds, "track": "C-I", "runs": n_runs, "baselines": ["Markov order 1", "Markov order 2", "training-window historical rates"],
                           "historical_cutoffs": calib.get("historical_cutoffs", [])},
              "headline": headline, "metrics": metrics, "charts": charts, "scenario_comparison": scen_rows, "process_map": pm, "periods": periods, "change": change,
              "business_validation": business_validation,
              "per_run": [{k: v for k, v in r.items() if k != "headline"} for r in per_run],
              "runtime_s_mean": _mean([r["runtime_s"] for r in per_run])}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1, default=_json_default))
    return result


def _json_default(o: Any) -> Any:
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if np.isnan(o) else float(o)
    if isinstance(o, float) and math.isnan(o):
        return None
    if isinstance(o, (pd.Timestamp, datetime)):
        return o.isoformat()
    if isinstance(o, (set, np.ndarray)):
        return list(o)
    return str(o)


# ----------------------------------------------------------------------------- results view (Results tab)

def results_view(ctx: InstanceContext) -> dict[str, Any]:
    """Held-out truth and matched predictions, using only the current evaluation's run IDs."""
    from ..evaluation.results import base_document, interval_of, mean_of, run_docs, series_mean
    doc = base_document(ctx)
    ev_path = ctx.runs_dir / "evaluation.json"
    ev = json.loads(ev_path.read_text()) if ev_path.exists() else {}
    base = doc["scenarios"]["baseline"]; alt = doc["scenarios"].get("alternative")
    evm = {m["id"]: m for m in ev.get("metrics", [])}
    proto = ev.get("protocol") or {}
    run_ids = ev.get("run_ids", {})
    alt_runs = run_docs(ctx, alt["id"], "summary", run_ids.get(alt["id"], [])) if alt else []
    base_runs = run_docs(ctx, base["id"], "summary", run_ids.get(base["id"], []))
    alt_t0s = sorted({str(r.get("headline", {}).get("t0", ""))[:10] for r in alt_runs})
    sources = [{"id": "actual", "label": f"{base['title']} · actual outcome outcome", "kind": "actual", "scenario": base["id"], "note": f"Held-out events of the same cases in the {proto.get('horizon_days', 14)}-day horizons after each cutoff ({', '.join(proto.get('cutoffs', []))})."},
               {"id": "baseline", "label": f"{base['title']} · simulation prediction", "kind": "simulated", "scenario": base["id"], "runs": proto.get("runs"),
                "note": f"Simulation replay: mean over {proto.get('runs', '?')} runs ({len(proto.get('cutoffs', []))} cutoffs x {len(proto.get('seeds', []))} seeds); the simulation never reads events after t0."}]
    if alt:
        sources.append({"id": "alternative", "label": f"{alt['title']} · simulation prediction", "kind": "simulated", "scenario": alt["id"], "runs": len(alt_runs),
                        "note": f"Mean over {len(alt_runs)} completed runs of the alternative (cutoffs {', '.join(alt_t0s) or 'none yet'}); 5%-95% range across runs."})
    H = int(proto.get("horizon_days", 14))
    periods = ev.get("periods") or {}; change = ev.get("change") or {}
    pb, pa = periods.get("before") or {}, periods.get("after") or {}
    doc["design"] = (f"The simulation was tuned on the operation before the change (model choices on July-August validation, then refitted through August 31). "
                     f"Before: the real operation at {len(pb.get('cutoffs', []))} August cutoffs. Then the change. After: from each of {len(pa.get('cutoffs', []))} September-October cutoffs the simulation took every live purchase-order item and continued it for {H} days, "
                     f"choosing every subsequent step, actor and timing itself with the workforce actually active before the cutoff, {len(proto.get('seeds', []))} seeds each. Incoming orders are supplied as observed; their subsequent events are hidden and used only for scoring.")
    if pb.get("metrics") and pa.get("metrics"):
        def sv(period: dict, mid: str, key: str):
            return (period.get("metrics", {}).get(mid) or {}).get(key)
        story_metrics = []
        for mid, label, unit, better in (("completion_14d", f"Live items completed within {H} days", "%", "higher"), ("median_cycle_hours", "Median cycle time of completed items", "h", "lower"),
                                         ("exception_rate", "Items with an exception in the horizon", "%", "lower"), ("handoffs_per_case", "Hand-offs per active item", "", "lower"), ("events_per_week", "Events per week", "", "higher")):
            story_metrics.append({"id": mid, "label": label, "unit": unit, "better": better, "before_actual": sv(pb, mid, "actual"), "before_sim": sv(pb, mid, "simulated"), "after_actual": sv(pa, mid, "actual"), "after_sim": sv(pa, mid, "simulated"),
                                  "intervals": {"before_sim": sv(pb, mid, "interval"), "after_sim": sv(pa, mid, "interval")}})
        story_metrics.append({"id": "staff_active", "label": "Active people in the two weeks before the cutoff (the change itself)", "unit": "", "better": "", "before_actual": pb.get("staff_active"), "before_sim": pb.get("staff_active"), "after_actual": pa.get("staff_active"), "after_sim": pa.get("staff_active"), "intervals": {}, "note": "The simulation is staffed with the people really active before each cutoff, so this row is the same on both sides by construction."})
        story_metrics.append({"id": "arrivals", "label": f"New items arriving in the {H} days", "unit": "", "better": "", "before_actual": pb.get("arrivals"), "before_sim": pb.get("arrivals"), "after_actual": pa.get("arrivals"), "after_sim": pa.get("arrivals"), "intervals": {}, "note": "Arrivals are replayed as they really happened."})
        acc_b, acc_a = sv(pb, "next_activity_accuracy", "simulated"), sv(pa, "next_activity_accuracy", "simulated")
        ca = pa.get("metrics", {}).get("completion_14d") or {}
        ratio = float(change.get("ratio") or 1.0)
        hist = {m["id"]: m.get("baseline") for m in ev.get("metrics", [])}
        scale_up = {"completion_14d", "events_per_week"}; scale_down = {"median_cycle_hours"}
        baselines = [
            {"id": "carry_forward", "label": "No change: the before period carried forward", "values": {m["id"]: m["before_actual"] for m in story_metrics if m["better"]}},
            {"id": "training_average", "label": "Pre-policy historical average (January-August 2018)", "values": {m["id"]: hist.get(m["id"]) for m in story_metrics if m["better"]}},
            {"id": "scale_with_staff", "label": f"Scale with staff: before x {ratio:.2f} for throughput, / {ratio:.2f} for cycle time", "values": {m["id"]: (m["before_actual"] * ratio if m["id"] in scale_up else m["before_actual"] / ratio if m["id"] in scale_down else m["before_actual"]) if m["before_actual"] is not None else None for m in story_metrics if m["better"]}},
        ]
        doc["story"] = {"before": {"label": "Before the change", "sublabel": f"The operation the simulation was tuned on · actual outcome at {', '.join(pb.get('cutoffs', []))}"},
                        "change": {"label": change.get("label", "The change"), "description": change.get("description", ""),
                                   "stats": [{"label": "Active people", "value": f"{pb.get('staff_active', 0):.0f} → {pa.get('staff_active', 0):.0f}"}, {"label": "Workforce", "value": f"{change.get('ratio', 0):.2f}x"}]},
                        "after": {"label": "After the change", "sublabel": f"{', '.join(pa.get('cutoffs', []))} · {pa.get('runs')} runs"},
                        "columns": {"before_actual": "Actual outcome", "after_actual": "Actual outcome", "after_sim": "Simulation prediction"},
                        "metrics": story_metrics, "chart": "completion_curve", "baselines": baselines, "baseline_basis": "after",
                        "business_validation": ev.get("business_validation", []),
                        "fidelity": [{"label": "Next real step predicted correctly, after the change", "value": acc_a, "unit": "%"},
                                     {"label": "Simple frequency model (most common next step after the last two)", "value": (evm.get("next_activity_accuracy") or {}).get("baseline"), "unit": "%"},
                                     {"label": f"Completed in {H} days: predicted vs actual, after", "value": f"{ca.get('simulated', 0):.1f}% vs {ca.get('actual', 0):.1f}%" if ca else None, "unit": ""}]}
    metrics: list[dict[str, Any]] = []
    def add(mid: str, label: str, unit: str, better: str, actual, base_v, alt_v, base_iv=None, alt_iv=None, note: str = "") -> None:
        metrics.append({"id": mid, "label": label, "unit": unit, "better": better, "values": {"actual": actual, "baseline": base_v, "alternative": alt_v},
                        "intervals": {k: v for k, v in (("baseline", base_iv), ("alternative", alt_iv)) if v}, "note": note})
    def ev_vals(mid: str):
        m = evm.get(mid) or {}
        return m.get("actual"), m.get("simulated"), m.get("interval")
    a, b, iv = ev_vals("completion_14d"); add("completion_14d", f"Live cases completed within {H} days", "%", "higher", a, b, mean_of(alt_runs, "headline.completion_rate_14d", 2), iv, interval_of(alt_runs, "headline.completion_rate_14d", 2))
    a, b, iv = ev_vals("median_cycle_hours"); add("median_cycle_hours", "Median cycle time of completed cases", "h", "lower", a, b, mean_of(alt_runs, "headline.median_cycle_hours_completed", 0), iv, interval_of(alt_runs, "headline.median_cycle_hours_completed", 0))
    a, b, iv = ev_vals("exception_rate"); add("exception_rate", "Cases with an exception in the horizon", "%", "lower", a, b, mean_of(alt_runs, "headline.exception_rate", 2), iv, interval_of(alt_runs, "headline.exception_rate", 2))
    a, b, iv = ev_vals("handoffs_per_case"); add("handoffs_per_case", "Hand-offs per active case", "", "lower", a, b, mean_of(alt_runs, "headline.handoffs_per_case", 3), iv, interval_of(alt_runs, "headline.handoffs_per_case", 3))
    a, b, iv = ev_vals("events_per_week"); add("events_per_week", "Events per week", "", "higher", a, b, (lambda v: round(v / max(1, H / 7), 0) if v is not None else None)(mean_of(alt_runs, "headline.events", 0)), iv, None)
    add("backlog_end", "Open cases at the end of the horizon", "", "lower", None, mean_of(base_runs, "headline.backlog_end", 0), mean_of(alt_runs, "headline.backlog_end", 0), interval_of(base_runs, "headline.backlog_end", 0), interval_of(alt_runs, "headline.backlog_end", 0),
        note="Simulated only; matching cutoffs and seeds from the current evaluation.")
    add("mean_wait_h", "Mean wait before an action (hours)", "h", "lower", None, mean_of(base_runs, "headline.mean_wait_h", 2), mean_of(alt_runs, "headline.mean_wait_h", 2), interval_of(base_runs, "headline.mean_wait_h", 2), interval_of(alt_runs, "headline.mean_wait_h", 2), note="Simulated only.")
    add("util_ap_invoice", "Utilization, AP invoice clerks", "%", "lower", None, (lambda v: round(v * 100, 1) if v is not None else None)(mean_of(base_runs, "headline.utilization.ap_invoice", 4)), (lambda v: round(v * 100, 1) if v is not None else None)(mean_of(alt_runs, "headline.utilization.ap_invoice", 4)), note="Simulated only; share of working-hour capacity used.")
    a, b, iv = ev_vals("next_activity_accuracy"); add("next_activity_accuracy", "Next-step prediction accuracy on open cases", "%", "higher", None, b, None, iv, None,
        note=f"Validation of the simulation against the held-out log; a simple frequency model (most common next step after the last two steps, learned on the same pre-policy data) gets {(lambda v: f'{v:.1f}%' if isinstance(v, (int, float)) else v)((evm.get('next_activity_accuracy') or {}).get('baseline'))}.")

    charts: list[dict[str, Any]] = []
    evc = {c["id"]: c for c in ev.get("charts", [])}
    cc = evc.get("completion_curve")
    if cc:
        series = [{"name": "Simulation prediction", "y": cc["series"][0]["y"], "source": "baseline"}, {"name": "Actual outcome", "y": cc["series"][1]["y"], "source": "actual"}]
        alt_curves = [r for r in alt_runs if isinstance(r.get("headline", {}).get("completion_curve"), list)]
        if alt_curves:
            med, lo, hi = series_mean(alt_curves, lambda d: d["headline"]["completion_curve"])
            series.append({"name": alt["short_title"], "y": med, "band": [lo, hi], "source": "alternative"})
        charts.append({"id": "completion_curve", "type": "line", "title": cc["title"], "x": cc["x"], "x_label": cc.get("x_label"), "y_label": cc.get("y_label"), "series": series, "kind": "trajectory", "note": cc.get("note", "")})
    wt = evc.get("weekly_throughput")
    if wt:
        series = [{"name": "Simulation prediction", "y": wt["series"][0]["y"], "source": "baseline"}, {"name": "Actual outcome", "y": wt["series"][1]["y"], "source": "actual"}]
        if alt_runs:
            ev_week = mean_of(alt_runs, "headline.events", 0)
            if ev_week is not None:
                weekly = [r["headline"]["weekly_events"] for r in alt_runs if r.get("headline", {}).get("weekly_events")]
                if weekly:
                    series.append({"name": alt["short_title"], "y": np.mean(weekly, axis=0).tolist(), "source": "alternative"})
        charts.append({"id": "weekly_throughput", "type": "bar", "title": wt["title"], "x": wt["x"], "x_label": "", "y_label": "events", "series": series, "kind": "bars", "note": "Same eligible cases, cutoffs and seeds for both scenarios."})
    av = evc.get("activity_volumes")
    if av:
        charts.append({"id": "activity_volumes", "type": "hbar", "title": av["title"], "x": av["x"], "x_label": av.get("x_label"), "y_label": "", "series": [{"name": "Simulation prediction", "y": av["series"][0]["y"], "source": "baseline"}, {"name": "Actual outcome", "y": av["series"][1]["y"], "source": "actual"}], "kind": "bars", "note": av.get("note", "")})
    util_roles = ["purchasing_clerk", "buyer", "goods_receipt", "ap_invoice", "ap_payment"]
    if base_runs or alt_runs:
        series = []
        for sid, docs, label in (("baseline", base_runs, "As operated (simulated)"), ("alternative", alt_runs, alt["short_title"] if alt else "")):
            if docs:
                series.append({"name": label, "y": [(lambda v: round(v * 100, 1) if v is not None else None)(mean_of(docs, f"headline.utilization.{r}", 4)) for r in util_roles], "source": sid})
        charts.append({"id": "utilization", "type": "bar", "title": "Utilization by role (% of working-hour capacity)", "x": util_roles, "x_label": "", "y_label": "%", "series": series, "kind": "bars", "note": "Simulated only."})
    kind_labels = {"actual": "Actual outcome (actual data)", "baseline": "Simulation prediction", "alternative": "Alternative simulation prediction"}
    shorts = {"actual": "Actual outcome", "baseline": "Simulation prediction", "alternative": alt["short_title"] if alt else "Alternative"}
    for src in sources:
        src["kind_label"] = kind_labels.get(src["id"], src["kind"]); src["short"] = shorts.get(src["id"], src["id"])
    mv = {m["id"]: m["values"] for m in metrics}
    acc = (evm.get("next_activity_accuracy") or {})
    cb, ca = (pb.get("metrics", {}).get("completion_14d") or {}), (pa.get("metrics", {}).get("completion_14d") or {})
    hero = {"kicker": f"{change.get('label', 'The change')}: {change.get('ratio', 0):.2f}x the workforce" if change.get("ratio") else "Replay of a real operation it had never seen",
            "stats": ([{"label": f"Completed in {H} days before the change, actual", "value": cb.get("actual"), "unit": "%"},
                       {"label": "After the change, actual", "value": ca.get("actual"), "unit": "%"},
                       {"label": "After the change, predicted by the simulation", "value": ca.get("simulated"), "unit": "%"},
                       {"label": "Next real step predicted correctly", "value": acc.get("simulated"), "unit": "%"}] if cb and ca else
                      [{"label": "Next real step predicted correctly", "value": acc.get("simulated"), "unit": "%"}, {"label": "Simple frequency model (most common next step after the last two)", "value": acc.get("baseline"), "unit": "%"}]),
            "claim": "Model selected on pre-policy validation windows and refitted through August 31. Only after-change predictions are scored; future case events are withheld at each cutoff.",
            "chart": "completion_curve"}
    if alt and mv["completion_14d"]["alternative"] is not None:
        u_b, u_a = mv["util_ap_invoice"]["baseline"], mv["util_ap_invoice"]["alternative"]
        hero["alternative"] = {"kicker": f"Alternative: {alt['short_title']}",
                               "stats": [{"label": f"Live items completed in {H} days", "value": f"{mv['completion_14d']['baseline']:.1f}% → {mv['completion_14d']['alternative']:.1f}%", "unit": ""},
                                         {"label": "AP invoice clerk utilization", "value": f"{u_b:.0f}% → {u_a:.0f}%" if u_b is not None and u_a is not None else None, "unit": ""}],
                               "text": f"With the scenario's reduced staffing, the simulation estimates {H}-day completion of {mv['completion_14d']['alternative']:.1f}% versus {mv['completion_14d']['baseline']:.1f}% under observed staffing. AP invoice clerk utilization moves from {u_b:.0f}% to {u_a:.0f}%. This alternative is a model estimate; the observed period difference also includes changes in order mix.",
                               "chart": "utilization"}
    doc.update({"sources": sources, "metrics": metrics, "effects": [], "charts": charts, "hero": hero, "evaluation": {"generated": ev.get("generated"), "protocol": proto}})
    return doc
