"""Workforce world: a population of employees with latent states reacting to policies over time.

Generic over instances. Everything organisation-specific comes from the instance folder:

  data/normalized/population.parquet   one row per person: covariates, arm, role_id, org_unit, team_id, seat
  ontology/bindings.yaml               roles (onet_code), activities per role (dwa_ids, properties.weight), latent_states
  calibration/dynamics.yaml            derived variables, latent states, hazards, survey and review expressions
  calibration/priors.yaml              parameter central values + ranges; one draw per seed (sampled once per run)
  scenario `world:` block              start, end, arm_field, policy {type, days, who, phase_in}, survey_dates,
                                       survey_response_rate, review_period, holidays, work_events (all|sample|none)
  scenario `interventions:`            [{type: wfh_offer, days, who}, {type: no_policy}] applied over `policy`

Mechanics. Hourly clock, working hours 9-18 Mon-Fri. Every working hour each active agent performs one
activity drawn from its role's bound activities (one `complete` row per agent-hour, 1h). On WFH-eligible
days the offered agents choose `wfh` vs `office` through their seat's Policy among options the world
supplies with prior-driven weights. Office days generate commute events at the day boundaries. At the end of
each week latent states update per dynamics.yaml (team means of states are available to the expressions, so
sentiment can spread along same_manager edges), the weekly quit hazard is offered to the Policy as
{quit, stay}, and `state`/`decide` events are emitted. Surveys and reviews fire from the scheduler.

Expressions in dynamics.yaml are evaluated per agent with numpy over the namespace documented in
`_Namespace`. The reference outcomes an instance is scored against are read only inside `evaluate()`.

Digital twin (v2, 2026-10-25). Each agent is a persistent twin: a trait layer computed once per run from its real
covariates and sampled priors (e.g. a WFH-preference trait that drives both take-up and the value of each WFH day,
baseline satisfaction, baseline quit hazard), a text profile built from those traits (`twin_profile`), weekly latent
states with inertia, and team context (team means, share of teammates offered the policy). Seat policies receive the
profile, trait baselines and last week's states in Observation.context, so an LLM seat reasons from the same twin the
rule seat draws from. `twins.json` in every run folder lists every twin with traits, final states and outcomes.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.special import ndtr, ndtri

from .. import RUNS_DIR
from ..evaluation.metrics import coverage, interval
from ..instances import InstanceContext
from ..kernel.world import Agent, BaseWorld, RunSummary
from ..policies import Action, Observation, load_registry
from ..store.runs import RunWriter
from ..store.trace import TRACE_COLUMNS

DAY_INDEX = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
DAY_NAMES = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
WORK_HOURS = (9, 18)


# ----------------------------------------------------------------------------- helpers

def _d(x: Any) -> date:
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    return date.fromisoformat(str(x)[:10])


def _days(days: list[str] | None) -> set[int]:
    return {DAY_INDEX[str(d)[:3].lower()] for d in (days or [])}


def _dig(obj: Any, path: str) -> Any:
    cur = obj
    for part in path.split("."):
        if cur is None:
            return None
        cur = cur.get(part) if isinstance(cur, dict) else None
    return cur


def _fnum(x: Any) -> float | None:
    try:
        v = float(x)
        return None if math.isnan(v) else v
    except (TypeError, ValueError):
        return None


def _rnd(x: Any, nd: int = 3) -> Any:
    v = _fnum(x)
    return None if v is None else round(v, nd)


def ordinal_review(prior: np.ndarray, rho: float, shift: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Ordinal rating transition preserving the observed pre-policy grade mix.

    A Gaussian copula supplies persistence; thresholds come exclusively from the
    prior ratings. Missing ratings are sampled from that same baseline mix.
    """
    prior = np.asarray(prior, dtype=float)
    observed = np.isfinite(prior) & (prior == np.round(prior)) & (prior >= 1) & (prior <= 5)
    counts = np.bincount(prior[observed].astype(int), minlength=6)[1:6].astype(float)
    probs = counts / counts.sum() if counts.sum() else np.full(5, 0.2)
    bounds = np.r_[0.0, np.cumsum(probs)]
    u = rng.random(len(prior))
    grade = np.clip(np.nan_to_num(prior, nan=3).astype(int) - 1, 0, 4)
    u = np.where(observed, bounds[grade] + u * probs[grade], u)
    rho = np.clip(rho, -0.999, 0.999)
    sd = max(float(np.nanstd(prior[observed])) if observed.any() else 1.0, 0.1)
    z = rho * ndtri(np.clip(u, 1e-12, 1 - 1e-12)) + np.sqrt(1 - rho * rho) * rng.normal(size=len(prior)) + np.asarray(shift) / sd
    return np.searchsorted(bounds[1:-1], ndtr(z), side="right") + 1


class _Namespace:
    """Evaluation namespace for dynamics.yaml expressions: per-agent arrays, parameters, numpy functions."""

    def __init__(self, rng: np.random.Generator, n: int) -> None:
        self.rng, self.n = rng, n
        self.funcs = {
            "exp": np.exp, "log": np.log, "sqrt": np.sqrt, "clip": np.clip, "where": np.where, "maximum": np.maximum,
            "minimum": np.minimum, "abs": np.abs, "round": np.round, "tanh": np.tanh, "floor": np.floor,
            "mean": lambda x: float(np.nanmean(x)), "std": lambda x: float(np.nanstd(x)) or 1.0,
            "median": lambda x: float(np.nanmedian(x)), "quantile": lambda x, q: float(np.nanquantile(x, q)), "logistic": lambda x: 1.0 / (1.0 + np.exp(-np.asarray(x, dtype=float))),
            "logit": lambda p: np.log(np.asarray(p, dtype=float) / (1.0 - np.asarray(p, dtype=float))),
            "normal": lambda sd, mu=0.0: rng.normal(mu, sd, n), "uniform": lambda: rng.random(n), "pi": math.pi,
            "ordinal_review": lambda prior, rho, shift: ordinal_review(prior, rho, shift, rng),
        }

    def eval(self, expr: Any, arrays: dict[str, Any]) -> np.ndarray:
        ns = dict(self.funcs); ns.update(arrays)
        out = eval(str(expr), {"__builtins__": {}}, ns)  # noqa: S307 - instance-authored config, not user input
        out = np.asarray(out, dtype=float)
        if out.ndim == 0:
            out = np.full(self.n, float(out))
        return out


def sample_priors(cfg: dict[str, Any], rng: np.random.Generator, mode: str = "sample") -> dict[str, float]:
    """One value per parameter: central (mode='central') or a triangular draw on [lo, hi] with mode at central."""
    out: dict[str, float] = {}
    for name, spec in (cfg.get("parameters") or {}).items():
        c = float(spec["central"]); lo, hi = (float(v) for v in spec.get("range", [c, c]))
        if mode == "central" or hi <= lo:
            out[name] = c
        else:
            out[name] = float(rng.triangular(lo, min(max(c, lo), hi), hi))
    return out


def resolve_policy(world_cfg: dict[str, Any], interventions: list[dict[str, Any]] | None) -> dict[str, Any]:
    pol = dict(world_cfg.get("policy") or {"type": "no_policy"})
    for iv in interventions or []:
        t = iv.get("type")
        if t == "no_policy":
            pol = {"type": "no_policy"}
        elif t == "wfh_offer":
            base = pol if pol.get("type") == "wfh_offer" else {}
            pol = {**base, **iv}
        else:
            raise ValueError(f"workforce world: unknown intervention type {t!r}")
    return pol


# ----------------------------------------------------------------------------- world

class World(BaseWorld):
    @classmethod
    def from_instance(cls, ctx: InstanceContext, scenario: dict[str, Any], seed: int) -> "World":
        return cls(ctx, scenario, seed)

    def __init__(self, ctx: InstanceContext, scenario: dict[str, Any], seed: int) -> None:
        w = scenario.get("world") or {}
        if "start" not in w or "end" not in w:
            raise ValueError("workforce world: scenario.world needs `start` and `end` dates")
        start = datetime.combine(_d(w["start"]), datetime.min.time())
        end = datetime.combine(_d(w["end"]) + timedelta(days=1), datetime.min.time())   # end date inclusive
        super().__init__(ctx, scenario, seed, start, end)
        self.clock.work_hours = WORK_HOURS
        self.w = w
        self.rng = np.random.default_rng(seed)
        # Trace sampling and observed survey noise must not move behavioral draws.
        self.trace_rng = np.random.default_rng(np.random.SeedSequence([seed, 1]))
        self.measure_rng = np.random.default_rng(np.random.SeedSequence([seed, 2]))
        self.pop = pd.read_parquet(ctx.data_normalized / "population.parquet").reset_index(drop=True)
        self.n = len(self.pop)
        self.bindings = ctx.yaml("ontology/bindings.yaml")
        self.dyn = ctx.yaml("calibration/dynamics.yaml")
        self.params = sample_priors(ctx.yaml("calibration/priors.yaml"), self.rng, str(w.get("priors", "sample")))
        self.registry = load_registry(ctx)
        self.policy = resolve_policy(w, scenario.get("interventions"))
        self.ns = _Namespace(self.rng, self.n)
        self.measure_ns = _Namespace(self.measure_rng, self.n)

        # --- population arrays ---
        self.ids = self.pop["person_id"].astype(str).to_numpy() if "person_id" in self.pop else np.array([f"p{i:04d}" for i in range(self.n)])
        self.roles = self.pop["role_id"].astype(str).to_numpy()
        self.units = self.pop["org_unit"].astype(str).to_numpy() if "org_unit" in self.pop else np.full(self.n, "")
        self.teams = self.pop["team_id"].astype(str).to_numpy() if "team_id" in self.pop else np.full(self.n, "")
        seat_cfgs = set((self.registry.seat_cfgs or {}).keys())
        seats_col = self.pop["seat"].astype(str).to_numpy() if "seat" in self.pop else np.full(self.n, "employee")
        self.seats = np.array([r if r in seat_cfgs else s for r, s in zip(self.roles, seats_col)])
        self.arm_field = str(w.get("arm_field", "treat"))
        self.arm_labels = {str(k): str(v) for k, v in (w.get("arm_labels") or {}).items()}
        self.arms = self.pop[self.arm_field].astype(int).to_numpy() if self.arm_field in self.pop else np.zeros(self.n, dtype=int)
        self.breakdowns = [b for b in (w.get("breakdowns") or []) if b in self.pop.columns]
        self.cov = self._covariates()
        for name, expr in (self.dyn.get("derived") or {}).items():
            self.cov[name] = self.ns.eval(expr, {**self.cov, **self.params})
        for i, row in enumerate(self.pop.itertuples(index=False)):
            self.agents[self.ids[i]] = Agent(id=self.ids[i], role=self.roles[i], org_unit=self.units[i], seat=self.seats[i],
                                             attributes={"team_id": self.teams[i], "arm": int(self.arms[i])})

        # --- policy: who is offered, on which days, from when ---
        self.offer_days = _days(self.policy.get("days")) if self.policy.get("type") == "wfh_offer" else set()
        self.offer_mask = self._who(self.policy.get("who", "treat")) if self.offer_days else np.zeros(self.n, dtype=bool)
        self.phase_start = np.full(self.n, _d(self.policy.get("start", w["start"])), dtype=object)
        for ph in self.policy.get("phase_in") or []:
            f = ph.get("field")
            if f in self.pop.columns:
                m = self.pop[f].to_numpy() == ph.get("value")
                self.phase_start[m] = _d(ph["start"])
        self.policy_end = _d(self.policy.get("end", w["end"]))
        self.holidays = {_d(x) for x in (w.get("holidays") or [])}
        self.survey_dates = [_d(x) for x in (w.get("survey_dates") or [])]
        self.response_rate = float(w.get("survey_response_rate", 1.0))
        rp = w.get("review_period") or {}
        self.review_date = _d(rp["date"]) if rp.get("date") else None
        self.review_id = str(rp.get("id", "review"))
        mode = str(w.get("work_events", "all"))
        if mode == "sample":
            self.work_mask = self.trace_rng.random(self.n) < float(w.get("work_events_sample", 0.1))
        elif mode == "none":
            self.work_mask = np.zeros(self.n, dtype=bool)
        else:
            self.work_mask = np.ones(self.n, dtype=bool)
        self.work_mode = mode

        # --- activities per role (weights from bindings properties.weight) ---
        self.acts: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        for role in np.unique(self.roles):
            items = [a for a in self.bindings.get("activities", []) if role in (a.get("roles") or [])]
            if not items:
                items = [{"id": "work", "properties": {"weight": 1}}]
            ids = np.array([a["id"] for a in items], dtype=object)
            wts = np.array([float((a.get("properties") or {}).get("weight", 1.0)) for a in items])
            self.acts[role] = (ids, np.cumsum(wts) / wts.sum())
        self.role_idx = {role: np.flatnonzero(self.roles == role) for role in self.acts}

        # --- state ---
        self.active = np.ones(self.n, dtype=bool)
        self.quit_week = np.full(self.n, -1, dtype=int)
        self.states: dict[str, np.ndarray] = {}
        for name, spec in (self.dyn.get("states") or {}).items():
            self.states[name] = self.ns.eval(spec.get("init", "0"), {**self.cov, **self.params}) if spec else np.zeros(self.n)
        self.reported = [n for n, s in (self.dyn.get("states") or {}).items() if (s or {}).get("report")]
        self.traits = self._trait_table()
        self.profiles = self._profiles()
        for i, aid in enumerate(self.ids):
            self.agents[aid].attributes["profile"] = self.profiles[i]
        self.week = 0
        self.eligible_week = np.zeros(self.n); self.wfh_week = np.zeros(self.n)
        self.office_week = np.zeros(self.n); self.workdays_week = np.zeros(self.n)
        self.eligible_total = np.zeros(self.n); self.wfh_total = np.zeros(self.n)
        self.hazard = np.zeros(self.n)
        self.expected_quits = np.zeros(self.n)  # counting-process compensator: sum of hazard while at risk
        self.takeup_log: list[dict[str, Any]] = []
        self.weekly_log: list[dict[str, Any]] = []
        self.survey: dict[str, dict[str, np.ndarray]] = {}
        self.review: dict[str, np.ndarray] = {}
        self.decisions = {"wfh": 0, "office": 0, "quit": 0, "stay": 0}
        self._buf: list[pd.DataFrame] = []
        self.metrics: dict[str, Any] = {}
        self._team_env: dict[str, np.ndarray] | None = None
        for sd in self.survey_dates:
            self.scheduler.schedule(datetime.combine(sd, datetime.min.time()) + timedelta(hours=17), "survey", date=sd)
        if self.review_date:
            self.scheduler.schedule(datetime.combine(self.review_date, datetime.min.time()) + timedelta(hours=17), "review", date=self.review_date)

    # ------------------------------------------------------------------ configuration helpers
    def _covariates(self) -> dict[str, np.ndarray]:
        fills = self.dyn.get("covariates") or {}
        cov: dict[str, np.ndarray] = {}
        for c in self.pop.columns:
            s = self.pop[c]
            if s.dtype == bool:
                cov[c] = s.to_numpy().astype(float)
            elif pd.api.types.is_numeric_dtype(s):
                cov[c] = s.to_numpy(dtype=float, na_value=np.nan)
        for c, rule in fills.items():
            if c not in cov:
                continue
            arr = cov[c].copy(); miss = np.isnan(arr)
            if not miss.any():
                continue
            if isinstance(rule, str) and rule in cov:
                arr[miss] = cov[rule][miss]
            elif rule == "mean":
                arr[miss] = np.nanmean(arr)
            elif rule == "median":
                arr[miss] = np.nanmedian(arr)
            else:
                arr[miss] = float(rule)
            cov[c] = arr
        for c in cov:
            if np.isnan(cov[c]).any():
                cov[c] = np.nan_to_num(cov[c], nan=float(np.nanmean(cov[c])) if np.isfinite(np.nanmean(cov[c])) else 0.0)
        return cov

    def _who(self, who: Any) -> np.ndarray:
        terms = who if isinstance(who, list) else [who]
        mask = np.ones(self.n, dtype=bool)
        for t in terms:
            t = str(t)
            if t == "all":
                continue
            if t == "treat":
                mask &= self.arms == 1
            elif t == "control":
                mask &= self.arms == 0
            elif t == "managers":
                mask &= self.cov.get("managerial", np.zeros(self.n)) > 0
            elif t == "nonmanagers":
                mask &= self.cov.get("managerial", np.zeros(self.n)) == 0
            elif "=" in t:
                f, v = t.split("=", 1); mask &= self.pop[f].astype(str).to_numpy() == v
            else:
                raise ValueError(f"workforce world: unknown `who` term {t!r}")
        return mask

    def _label(self, arm: int) -> str:
        return self.arm_labels.get(str(arm), f"arm {arm}")

    # ------------------------------------------------------------------ digital twin: trait layer and profile
    TRAIT_KEYS = ("sat_base", "wlb_base", "takeup_propensity", "wfh_pref_z", "wfh_value", "benefit_mult", "h0_week", "commute_2way_h")

    def _trait_table(self) -> dict[str, np.ndarray]:
        """Per-person trait layer: derived variables computed once per run (dynamics.yaml `derived`) that stay fixed."""
        return {k: np.asarray(self.cov[k], dtype=float) for k in self.TRAIT_KEYS if k in self.cov}

    def _profiles(self) -> list[str]:
        """Text persona per agent, built deterministically from real covariates and the trait layer (no model call).
        Protected fields (gender) are not written into the profile; see design principle 5."""
        role_label = {r["id"]: r.get("label", r["id"]) for r in self.bindings.get("roles", [])}
        unit_label = {u["id"]: u.get("label", u["id"]) for u in self.bindings.get("org_units", [])}
        c = self.cov
        tr = self.traits
        pref_pct = (np.argsort(np.argsort(tr["wfh_pref_z"])) / max(1, self.n - 1) * 100) if "wfh_pref_z" in tr else np.full(self.n, 50.0)
        haz_pct = (np.argsort(np.argsort(tr["h0_week"])) / max(1, self.n - 1) * 100) if "h0_week" in tr else np.full(self.n, 50.0)
        out = []
        for i in range(self.n):
            bits = [f"{role_label.get(self.roles[i], self.roles[i])} in the {unit_label.get(self.units[i], self.units[i] or 'company')}, team {self.teams[i]}."]
            if "age" in c and "tenure_years" in c:
                bits.append(f"Age {int(c['age'][i])}, {c['tenure_years'][i]:.1f} years with the company" + (", graduate degree" if c.get("grad", np.zeros(self.n))[i] > 0 else "") + ".")
            if "children_ind" in c:
                bits.append("Has children at home." if c["children_ind"][i] > 0 else "No children at home.")
            if "commute_hour" in c:
                bits.append(f"One-way commute about {int(round(60 * c['commute_hour'][i]))} minutes.")
            if "prior_performance" in c:
                bits.append(f"Last review grade {c['prior_performance'][i]:.0f} of 5.")
            if "volunteer" in c:
                bits.append("Volunteered for the hybrid-work experiment." if c["volunteer"][i] > 0 else "Did not volunteer for the experiment.")
            if "sat_base" in tr:
                bits.append(f"Baseline job satisfaction {tr['sat_base'][i]:.1f}/10, work-life balance {tr['wlb_base'][i]:.1f}/10.")
            bits.append(f"Preference for working from home: {'strong' if pref_pct[i] >= 75 else 'above average' if pref_pct[i] >= 50 else 'below average' if pref_pct[i] >= 25 else 'weak'} (percentile {pref_pct[i]:.0f}).")
            bits.append(f"Baseline attachment to the job: {'low' if haz_pct[i] >= 75 else 'average' if haz_pct[i] >= 25 else 'high'} (quit-risk percentile {haz_pct[i]:.0f}).")
            out.append(" ".join(bits))
        return out

    def _twin_context(self, i: int) -> dict[str, Any]:
        """What a seat policy may see about its own twin: profile, trait baselines, last week's states, team context."""
        ctx: dict[str, Any] = {"profile": self.profiles[i],
                               "traits": {k: round(float(v[i]), 3) for k, v in self.traits.items() if k in ("sat_base", "wlb_base", "takeup_propensity", "wfh_value")},
                               "last_week_states": {s: round(float(self.states[s][i]), 2) for s in self.reported}}
        if self._team_env is not None:
            ctx["team"] = {k: round(float(v[i]), 3) for k, v in self._team_env.items()}
        return ctx

    def _twins_table(self) -> list[dict[str, Any]]:
        rows = []
        for i in range(self.n):
            rows.append({"agent_id": self.ids[i], "role": self.roles[i], "org_unit": self.units[i], "team_id": self.teams[i], "arm": int(self.arms[i]), "seat": self.seats[i],
                         "profile": self.profiles[i], "traits": {k: _rnd(v[i], 4) for k, v in self.traits.items()},
                         "offered": bool(self.offer_mask[i]), "eligible_days": int(self.eligible_total[i]), "wfh_days": int(self.wfh_total[i]),
                         "quit_week": int(self.quit_week[i]) if self.quit_week[i] >= 0 else None,
                         "final_states": {s: _rnd(self.states[s][i]) for s in self.reported + ["exposure"] if s in self.states},
                         "final_quit_hazard_week": _rnd(self.hazard[i], 5)})
        return rows

    # ------------------------------------------------------------------ trace rows
    def _rows(self, tick: np.ndarray, times: Any, idx: np.ndarray, activity: Any, action_type: str, duration: Any = 0.0,
              attributes: Any = "{}", case_id: str = "", provenance: str = "simulated") -> None:
        n = len(idx)
        if n == 0:
            return
        df = pd.DataFrame({
            "tick": np.asarray(tick, dtype=np.int32), "sim_time": times, "agent_id": self.ids[idx], "role": self.roles[idx],
            "org_unit": self.units[idx], "case_id": case_id, "activity": activity, "action_type": action_type,
            "duration_h": np.asarray(duration, dtype=np.float32) if np.ndim(duration) else np.float32(duration),
            "wait_h": np.float32(0.0), "provenance": provenance, "attributes": attributes,
        }, columns=TRACE_COLUMNS)
        self._buf.append(df)
        self._n_events += n

    def _flush(self) -> None:
        if self._buf and self._writer is not None:
            self._writer.write_rows(pd.concat(self._buf, ignore_index=True))
        self._buf = []

    # ------------------------------------------------------------------ decisions through the seat's policy
    def _decide(self, idx: np.ndarray, options_for: Any, context_for: Any, when: datetime) -> list[Any]:
        out = []
        iso = when.isoformat()
        # Common random numbers by person and decision time: another employee
        # quitting or becoming eligible cannot shift this employee's next draw.
        draws = np.random.default_rng(np.random.SeedSequence([self.seed, when.toordinal(), when.hour])).random(self.n)
        for i in idx:
            pol = self.registry.for_seat(self.seats[i])
            opts = options_for(i)
            if getattr(pol, "name", None) == "rule":
                weights = np.array([o.get("weight", 1.0) for o in opts])
                choice = opts[min(int(np.searchsorted(np.cumsum(weights), draws[i] * weights.sum())), len(opts) - 1)]
                out.append(Action(kind=choice["kind"], target=choice.get("target"), params=choice.get("params", {})))
                continue
            obs = Observation(agent_id=self.ids[i], role=self.roles[i], sim_time=iso, context=context_for(i), options=opts)
            rng = np.random.default_rng(np.random.SeedSequence([self.seed, when.toordinal(), when.hour, int(i)]))
            out.append(pol.decide(obs, rng))
        return out

    # ------------------------------------------------------------------ main loop
    def run(self, writer: RunWriter) -> RunSummary:
        self._writer = writer
        day = self.clock.now.date()
        end_day = self.clock.end.date()
        while day < end_day:
            day_start = self.clock.now
            wd = day.weekday()
            workday = wd in self.clock.work_days and day not in self.holidays
            if workday:
                self._work_day(day, day_start)
            for ev in self.scheduler.due(day_start + timedelta(hours=23, minutes=59)):
                if ev.kind == "survey":
                    self._survey(day, day_start)
                elif ev.kind == "review":
                    self._review(day, day_start)
            if wd == 4 or (day + timedelta(days=1) >= end_day and self.workdays_week.any()):
                self._weekly(day, day_start)
                self._flush()
            for _ in range(24):
                self.clock.advance()
            day = self.clock.now.date()
        self._flush()
        self.metrics = self._metrics()
        writer.write_json("metrics.json", self.metrics)
        writer.write_json("twins.json", {"instance": self.ctx.id, "scenario": str(self.scenario.get("id", "")), "seed": self.seed, "n": self.n,
                                         "trait_keys": list(self.traits.keys()), "twins": self._twins_table()})
        headline = self._headline()
        return RunSummary(run_id=writer.run_id, instance=self.ctx.id, scenario=str(self.scenario.get("id", "")), seed=self.seed,
                          start=self.clock.start.isoformat(), end=(self.clock.end - timedelta(days=1)).isoformat(),
                          ticks=self.clock.tick, events=self._n_events, headline=headline)

    def _work_day(self, day: date, day_start: datetime) -> None:
        base = self.clock.tick
        active = self.active
        pool = active & self.offer_mask & (day.weekday() in self.offer_days) & (day <= self.policy_end)
        offered_today = pool & (self.phase_start <= day)
        wfh = np.zeros(self.n, dtype=bool)
        idx = np.flatnonzero(offered_today)
        if len(idx):
            prop_name = (self.dyn.get("takeup") or {}).get("propensity", "takeup_propensity")
            p = np.clip(self.cov.get(prop_name, np.full(self.n, 0.5)), 0.0, 1.0)
            commute = self.cov.get("commute_hour", np.zeros(self.n))
            def options(i: int) -> list[dict]:
                return [{"kind": "wfh", "label": "Work from home today", "weight": float(p[i])},
                        {"kind": "office", "label": "Come to the office today", "weight": float(1.0 - p[i])}]
            def context(i: int) -> dict:
                return {"day": day.strftime("%A %Y-%m-%d"), "one_way_commute_h": round(float(commute[i]), 2),
                        "children": int(self.cov.get("children_ind", np.zeros(self.n))[i]), "volunteered_for_trial": int(self.cov.get("volunteer", np.zeros(self.n))[i]),
                        "wfh_days_taken_so_far": int(self.wfh_total[i]), "eligible_days_so_far": int(self.eligible_total[i]),
                        "job_satisfaction": round(float(self.states.get("job_satisfaction", np.zeros(self.n))[i]), 2), **self._twin_context(i)}
            when = day_start + timedelta(hours=8)
            acts = self._decide(idx, options, context, when)
            choice = np.array([a.kind == "wfh" for a in acts])
            wfh[idx] = choice
            self.decisions["wfh"] += int(choice.sum()); self.decisions["office"] += int((~choice).sum())
            self.eligible_total[idx] += 1; self.wfh_total[idx] += choice
            self.eligible_week[idx] += 1; self.wfh_week[idx] += choice
            attrs = [json.dumps({"option": a.kind, "p_wfh": round(float(p[i]), 3), "rationale": a.rationale or ("prefers home office" if a.kind == "wfh" else "comes in"),
                                 **({"policy": a.params.get("fallback")} if a.params.get("fallback") else {})}) for i, a in zip(idx, acts)]
            self._rows(np.full(len(idx), base + 8), when, idx, "wfh_takeup", "decide", 0.0, attrs)
            pidx = np.flatnonzero(pool)
            for arm in np.unique(self.arms[pidx]):
                m = self.arms[pidx] == arm
                rec = {"date": day.isoformat(), "arm": int(arm), "n_eligible": int(m.sum()), "n_wfh": int(wfh[pidx][m].sum())}
                for b in self.breakdowns:
                    vals = self.pop[b].to_numpy()[pidx][m]
                    rec[b] = {str(v): [int((vals == v).sum()), int(wfh[pidx][m][vals == v].sum())] for v in pd.unique(vals) if not (isinstance(v, float) and np.isnan(v))}
                self.takeup_log.append(rec)
        self.workdays_week[active] += 1
        office = active & ~wfh
        self.office_week[office] += 1
        # commute events at the day boundaries (office days)
        oidx = np.flatnonzero(office)
        commute_h = self.cov.get("commute_hour", np.zeros(self.n))
        if self.work_mode != "none":
            oi = oidx[self.work_mask[oidx]]
            self._rows(np.full(len(oi), base + WORK_HOURS[0]), day_start + timedelta(hours=WORK_HOURS[0]), oi, "commute", "arrive", commute_h[oi], '{"direction": "to office"}')
            self._rows(np.full(len(oi), base + WORK_HOURS[1]), day_start + timedelta(hours=WORK_HOURS[1]), oi, "commute", "complete", commute_h[oi], '{"direction": "home"}')
        # hourly work: one `complete` row per agent-hour, activity drawn from the role's bound activities
        if self.work_mode != "none":
            hours = np.arange(WORK_HOURS[0], WORK_HOURS[1])
            widx = np.flatnonzero(active & self.work_mask)
            if len(widx):
                rep = np.repeat(widx, len(hours))
                hrs = np.tile(hours, len(widx))
                act = np.empty(len(rep), dtype=object)
                u = self.trace_rng.random(len(rep))
                for role, (ids, cum) in self.acts.items():
                    m = self.roles[rep] == role
                    if m.any():
                        act[m] = ids[np.minimum(np.searchsorted(cum, u[m]), len(ids) - 1)]
                loc = np.where(wfh[rep], '{"location": "home"}', '{"location": "office"}')
                times = pd.to_datetime(day_start) + pd.to_timedelta(hrs, unit="h")
                self._rows(base + hrs, times, rep, act, "complete", 1.0, loc)

    def _weekly(self, day: date, day_start: datetime) -> None:
        self.week += 1
        active = self.active
        offered = (self.offer_mask & (self.phase_start <= day) & (day <= self.policy_end)).astype(float)
        env = {
            "offered": offered, "days_offered": offered * float(len(self.offer_days)),
            "eligible_days_week": self.eligible_week, "wfh_days_week": self.wfh_week, "office_days_week": self.office_week,
            "workdays_week": self.workdays_week, "takeup_rate_cum": np.where(self.eligible_total > 0, self.wfh_total / np.maximum(self.eligible_total, 1), 0.0),
            "week": float(self.week), "team_size": np.zeros(self.n), "team_share_offered": np.zeros(self.n),
        }
        # team means of states over active teammates (same_manager edges)
        if active.any():
            tdf = pd.DataFrame({"team": self.teams[active], "_offered": offered[active], **{s: self.states[s][active] for s in self.states}})
            grp = tdf.groupby("team")
            size = grp["team"].transform("size").to_numpy()
            env["team_size"][active] = size
            env["team_share_offered"][active] = grp["_offered"].transform("mean").to_numpy()
            for s in self.states:
                tm = np.full(self.n, np.nan); tm[active] = grp[s].transform("mean").to_numpy()
                tm[~active] = self.states[s][~active]
                env[f"team_mean_{s}"] = tm
        self._team_env = {k: v for k, v in env.items() if k in ("team_size", "team_share_offered", "team_mean_job_satisfaction")}
        ns = {**self.cov, **self.params, **env}
        for name, spec in (self.dyn.get("states") or {}).items():
            ns[name] = self.states[name]
            if spec and spec.get("weekly"):
                new = self.ns.eval(spec["weekly"], ns)
                self.states[name] = np.where(active, new, self.states[name])
                ns[name] = self.states[name]
        quit_spec = (self.dyn.get("hazards") or {}).get("quit") or {}
        if quit_spec.get("weekly"):
            self.hazard = np.clip(self.ns.eval(quit_spec["weekly"], ns), 0.0, 1.0)
            self.expected_quits += np.where(active, self.hazard, 0.0)
        idx = np.flatnonzero(active)
        when = day_start + timedelta(hours=WORK_HOURS[1])
        if len(idx) and quit_spec.get("weekly"):
            h = self.hazard
            def options(i: int) -> list[dict]:
                return [{"kind": "quit", "label": "Resign this week", "weight": float(h[i])},
                        {"kind": "stay", "label": "Stay", "weight": float(1.0 - h[i])}]
            def context(i: int) -> dict:
                return {"week": self.week, **{s: round(float(self.states[s][i]), 2) for s in self.reported},
                        "offered_wfh": bool(offered[i]), "wfh_days_this_week": int(self.wfh_week[i]), "tenure_years": round(float(self.cov.get("tenure_years", np.zeros(self.n))[i]), 1), **self._twin_context(i)}
            acts = self._decide(idx, options, context, when)
            quit = np.array([a.kind == "quit" for a in acts])
            qidx = idx[quit]
            self.decisions["quit"] += int(quit.sum()); self.decisions["stay"] += int((~quit).sum())
            if len(qidx):
                self.active[qidx] = False
                self.quit_week[qidx] = self.week
                attrs = [json.dumps({"option": "quit", "weekly_hazard": round(float(h[i]), 5), "rationale": a.rationale or "left the company",
                                     **{s: round(float(self.states[s][i]), 2) for s in self.reported}}) for i, a in zip(qidx, [a for a in acts if a.kind == "quit"])]
                self._rows(np.full(len(qidx), self.clock.tick + WORK_HOURS[1]), when, qidx, "quit", "decide", 0.0, attrs)
        # weekly state snapshot for agents still active (plus those who just quit, final state)
        sidx = idx
        if len(sidx):
            cols = {s: np.round(self.states[s][sidx], 3) for s in self.reported}
            cols["exposure"] = np.round(self.states.get("exposure", np.zeros(self.n))[sidx], 3)
            cols["quit_hazard_week"] = np.round(self.hazard[sidx], 5)
            cols["wfh_days_week"] = self.wfh_week[sidx].astype(int)
            recs = pd.DataFrame(cols).to_dict("records")
            attrs = [json.dumps(r, default=float) for r in recs]
            self._rows(np.full(len(sidx), self.clock.tick + WORK_HOURS[1]), when, sidx, "latent_state", "state", 0.0, attrs)
        # weekly log by group
        rec = {"week": self.week, "week_end": day.isoformat()}
        for arm in np.unique(self.arms):
            m = self.arms == arm
            rec[str(arm)] = {"n": int(m.sum()), "quit_cum": int((~self.active[m]).sum()),
                             **{s: _rnd(float(self.states[s][m & self.active].mean()) if (m & self.active).any() else np.nan) for s in self.reported},
                             "exposure": _rnd(float(self.states.get("exposure", np.zeros(self.n))[m & self.active].mean()) if (m & self.active).any() else np.nan)}
        self.weekly_log.append(rec)
        self.eligible_week[:] = 0; self.wfh_week[:] = 0; self.office_week[:] = 0; self.workdays_week[:] = 0

    def _survey(self, day: date, day_start: datetime) -> None:
        active = self.active
        resp = active & (self.measure_rng.random(self.n) < self.response_rate)
        ns = {**self.cov, **self.params, **self.states}
        res: dict[str, np.ndarray] = {}
        for scale, expr in ((self.dyn.get("survey") or {}).get("scales") or {}).items():
            v = self.measure_ns.eval(expr, ns)
            res[scale] = np.where(resp, v, np.nan)
        self.survey[day.isoformat()] = res
        idx = np.flatnonzero(resp)
        if len(idx):
            recs = pd.DataFrame({k: v[idx] for k, v in res.items()}).to_dict("records")
            attrs = [json.dumps({"survey": day.isoformat(), **{k: (None if (isinstance(x, float) and np.isnan(x)) else float(x)) for k, x in r.items()}}) for r in recs]
            when = day_start + timedelta(hours=17)
            self._rows(np.full(len(idx), self.clock.tick + 17), when, idx, "survey_response", "state", 0.25, attrs)

    def _review(self, day: date, day_start: datetime) -> None:
        active = self.active
        ns = {**self.cov, **self.params, **self.states}
        rv = self.dyn.get("review") or {}
        grade = np.nan_to_num(self.measure_ns.eval(rv.get("performance_grade", "3"), ns), nan=3.0)
        ns["performance_grade"] = grade
        promo = self.measure_ns.eval(rv.get("promotion", "0"), ns) > 0.5 if rv.get("promotion") else np.zeros(self.n, dtype=bool)
        self.review = {"performance_grade": np.where(active, grade, np.nan), "promotion": np.where(active, promo.astype(float), np.nan)}
        idx = np.flatnonzero(active)
        if len(idx):
            attrs = [json.dumps({"period": self.review_id, "grade": int(grade[i]), "promoted": bool(promo[i])}) for i in idx]
            when = day_start + timedelta(hours=17)
            self._rows(np.full(len(idx), self.clock.tick + 17), when, idx, "performance_review", "complete", 0.5, attrs)

    # ------------------------------------------------------------------ outputs
    def _by_arm(self, values: np.ndarray, mask: np.ndarray | None = None, scale: float = 1.0) -> dict[str, Any]:
        mask = np.ones(self.n, dtype=bool) if mask is None else mask
        out: dict[str, Any] = {"n": {}}
        for arm in sorted(np.unique(self.arms)):
            m = mask & (self.arms == arm) & ~np.isnan(values)
            out[str(arm)] = _rnd(float(values[m].mean()) * scale if m.any() else np.nan, 4)
            out["n"][str(arm)] = int(m.sum())
        if "0" in out and "1" in out and out["0"] is not None and out["1"] is not None:
            out["itt"] = round(out["1"] - out["0"], 4)
        return out

    def _metrics(self) -> dict[str, Any]:
        quit = (~self.active).astype(float)
        m: dict[str, Any] = {"arms": {str(a): self._label(a) for a in sorted(np.unique(self.arms))}, "seed": self.seed, "scenario": self.scenario.get("id"),
                             "policy": self.policy, "headcount": self.n, "priors": self.params, "decisions": self.decisions}
        att = {"all": self._by_arm(quit, scale=100.0), "by": {}}
        for b in self.breakdowns:
            col = self.pop[b].to_numpy()
            vals = [v for v in pd.unique(col) if not (isinstance(v, float) and np.isnan(v))]
            att["by"][b] = {str(int(v)) if isinstance(v, (int, float, np.integer, np.floating)) else str(v): self._by_arm(quit, col == v, 100.0) for v in sorted(vals)}
            if pd.isna(col).any():
                att["by"][b]["missing"] = self._by_arm(quit, pd.isna(col), 100.0)
        m["attrition_pct"] = att
        m["quits"] = {str(a): int(quit[self.arms == a].sum()) for a in np.unique(self.arms)}
        expq = 100.0 * self.expected_quits
        exp_att = {"all": self._by_arm(expq), "by": {}, "_note": "sum of weekly hazards while at risk; unbiased aggregate expected-quit estimator with residual path uncertainty, not an individual probability"}
        for b in self.breakdowns:
            col = self.pop[b].to_numpy()
            vals = [v for v in pd.unique(col) if not (isinstance(v, float) and np.isnan(v))]
            exp_att["by"][b] = {str(int(v)) if isinstance(v, (int, float, np.integer, np.floating)) else str(v): self._by_arm(expq, col == v) for v in sorted(vals)}
        m["expected_attrition_pct"] = exp_att
        m["expected_quits_total"] = _rnd(float(expq.sum() / 100.0), 2)
        # survey scales (last survey date)
        sat: dict[str, Any] = {}
        if self.survey:
            last = sorted(self.survey)[-1]
            for scale, v in self.survey[last].items():
                sat[scale] = self._by_arm(v)
            sat["_date"] = last
        m["satisfaction"] = sat
        m["latent_end"] = {s: self._by_arm(np.where(self.active, self.states[s], np.nan)) for s in self.reported}
        m["latent_end"]["exposure"] = self._by_arm(np.where(self.active, self.states.get("exposure", np.zeros(self.n)), np.nan))
        if self.review:
            m["performance"] = {self.review_id: self._by_arm(self.review["performance_grade"])}
            m["promotion_pct"] = {self.review_id: self._by_arm(self.review["promotion"], scale=100.0)}
        # take-up series
        tk: dict[str, Any] = {"dates": [], "by_arm": {}, "by_group": {}}
        if self.takeup_log:
            df = pd.DataFrame(self.takeup_log)
            dates = sorted(df["date"].unique()); tk["dates"] = dates
            for arm in sorted(df["arm"].unique()):
                s = df[df.arm == arm].groupby("date")[["n_eligible", "n_wfh"]].sum().reindex(dates)
                tk["by_arm"][str(arm)] = [_rnd(r.n_wfh / r.n_eligible, 4) if r.n_eligible > 0 else None for r in s.itertuples()]
            for b in self.breakdowns:
                tk["by_group"][b] = {}
                for arm in sorted(df["arm"].unique()):
                    sub = df[df.arm == arm]
                    acc: dict[str, dict[str, list[int]]] = {}
                    for rec in sub.to_dict("records"):
                        for v, (ne, nw) in (rec.get(b) or {}).items():
                            acc.setdefault(v, {})[rec["date"]] = [ne, nw]
                    tk["by_group"][b][str(arm)] = {v: [(_rnd(d[dt][1] / d[dt][0], 4) if dt in d and d[dt][0] > 0 else None) for dt in dates] for v, d in acc.items()}
            all_days = df.groupby("date")[["n_eligible", "n_wfh"]].sum()
            tk["mean_by_arm"] = {str(arm): _rnd(df[df.arm == arm].n_wfh.sum() / max(1, df[df.arm == arm].n_eligible.sum()), 4) for arm in sorted(df["arm"].unique())}
            win = (df["date"] >= "2021-09-13") & (df["date"] < "2022-01-21")  # same window as the published group means
            tk["window_means_by_arm"] = {str(arm): _rnd(df[win & (df.arm == arm)].n_wfh.sum() / max(1, df[win & (df.arm == arm)].n_eligible.sum()), 4) for arm in sorted(df["arm"].unique())}
            for arm in m["arms"]:
                tk["window_means_by_arm"].setdefault(arm, 0.0); tk["mean_by_arm"].setdefault(arm, 0.0)
        else:
            tk["mean_by_arm"] = {a: 0.0 for a in m["arms"]}; tk["window_means_by_arm"] = {a: 0.0 for a in m["arms"]}
        m["takeup"] = tk
        # cumulative attrition by group per week
        cum = {"weeks": [r["week_end"] for r in self.weekly_log]}
        for arm in m["arms"]:
            cum[arm] = [_rnd(100.0 * r[arm]["quit_cum"] / r[arm]["n"], 3) for r in self.weekly_log]
            cum[f"{arm}_states"] = {s: [r[arm].get(s) for r in self.weekly_log] for s in self.reported + ["exposure"]}
        m["cumulative_attrition_pct"] = cum
        return m

    def _headline(self) -> dict[str, Any]:
        m = self.metrics
        h: dict[str, Any] = {"headcount": self.n, "quits": int((~self.active).sum()), "attrition_pct": _rnd(100.0 * (~self.active).mean(), 2),
                             "policy": (f"WFH offer on {', '.join(DAY_NAMES[d] for d in sorted(self.offer_days))} to {self.policy.get('who', 'treat')}" if self.offer_days else "no WFH policy"),
                             "work_events": self.work_mode, "by_arm": {}}
        sat = m.get("satisfaction", {}).get("work_satisfaction") or m["latent_end"].get("job_satisfaction", {})
        perf = (m.get("performance") or {}).get(self.review_id, {})
        for arm, label in m["arms"].items():
            h["by_arm"][label] = {"n": int((self.arms == int(arm)).sum()), "quits": m["quits"].get(arm, 0), "attrition_pct": m["attrition_pct"]["all"].get(arm),
                                  "mean_satisfaction": sat.get(arm), "take_up_rate": m["takeup"]["mean_by_arm"].get(arm), "mean_performance": perf.get(arm)}
        mg = m["attrition_pct"]["by"].get("managerial", {})
        if mg:
            h["attrition_pct_managers"] = {m["arms"][a]: mg.get("1", {}).get(a) for a in m["arms"]}
            h["attrition_pct_non_managers"] = {m["arms"][a]: mg.get("0", {}).get(a) for a in m["arms"]}
        return h


# ----------------------------------------------------------------------------- evaluation

def _run_once(ctx: InstanceContext, scenario: dict[str, Any], seed: int) -> dict[str, Any]:
    writer = RunWriter(ctx.id, str(scenario.get("id", "run")), config={"instance": ctx.id, "scenario": scenario, "seed": seed, "purpose": "evaluation"})
    world = World.from_instance(ctx, scenario, seed)
    summary = world.run(writer)
    world.metrics["run_id"] = writer.run_id
    writer.write_json("metrics.json", world.metrics)
    writer.close(summary.to_json())
    return world.metrics


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    from ..scenarios.loader import deep_merge
    return deep_merge(base, override or {})


def _value(metrics: dict[str, Any], spec: dict[str, Any]) -> float | None:
    node = _dig(metrics, spec["path"])
    return _fnum(node.get(str(spec.get("field", "itt")))) if isinstance(node, dict) else None


def _baseline_value(bspec: Any, control_level: float | None) -> float | None:
    if isinstance(bspec, (int, float)):
        return float(bspec)
    if isinstance(bspec, dict):
        if "absolute" in bspec:
            return float(bspec["absolute"])
        if "relative_to_control" in bspec and control_level is not None:
            return float(bspec["relative_to_control"]) * control_level
    return None


def _median(xs: list[float]) -> float | None:
    xs = [x for x in xs if x is not None]
    return float(np.median(xs)) if xs else None


def _mean(xs: list[float]) -> float | None:
    xs = [x for x in xs if x is not None]
    return float(np.mean(xs)) if xs else None


def static_attrition_baseline(ctx: InstanceContext, path: str) -> float | None:
    """Conventional prior-risk calculation; no trajectories or experiment outcomes."""
    if not path.startswith(("attrition_pct.", "expected_attrition_pct.")):
        return None
    pop = pd.read_parquet(ctx.data_normalized / "population.parquet")
    prior = {k: float(v["central"]) for k, v in ctx.yaml("calibration/priors.yaml")["parameters"].items()}
    risk = np.exp(-prior["tenure_slope"] * (pop.tenure_years - pop.tenure_years.mean())) * np.where(pop.managerial > 0, prior["manager_hazard_mult"], 1.0)
    probability = 1 - (1 - prior["quit_rate_semiannual"]) ** (risk / risk.mean())
    mask = pop.treat == 0
    parts = path.split(".")
    if len(parts) == 4 and parts[1] == "by" and parts[2] in pop:
        mask &= pop[parts[2]].astype(str) == str(float(parts[3])) if pd.api.types.is_float_dtype(pop[parts[2]]) else pop[parts[2]].astype(str) == parts[3]
    return float(probability[mask].mean() * 100) if mask.any() else None


def attrition_comparators(ctx: InstanceContext) -> dict[str, Any]:
    """A spreadsheet calculation using historical inputs only, without simulation or post-policy outcomes."""
    from ..scenarios import load_scenario
    spec = ctx.yaml("evaluation/comparators.yaml")
    history = ctx.yaml(spec["historical_reference"])["attrition"]
    study = spec["earlier_study"]
    days = len(load_scenario(ctx, "baseline")["world"]["policy"]["days"])
    old_days = float(study["home_days_per_week"])
    if not history["observed_before_policy"] or old_days <= 0 or not 0 <= days <= old_days:
        raise ValueError("Comparator requires pre-policy history and a supported home-day range")
    rate = float(history["value_pct"])
    reduction = float(study["relative_attrition_reduction"]) * days / old_days
    return {"history": history, "study": study, "method": spec["method"], "home_days": days,
            "relative_reduction": reduction, "no_change_pct": rate,
            "proportional_days_pct": rate * (1 - reduction), "proportional_days_effect_pp": -rate * reduction}


def comparison_values(ctx: InstanceContext, spec: dict[str, Any]) -> dict[str, float]:
    """Shared by evaluation and report refresh; never derives a comparator from scored outcomes."""
    out = {}
    for name, rule in (spec.get("baselines") or {}).items():
        if isinstance(rule, dict) and rule.get("method"):
            comp = attrition_comparators(ctx)
            out[name] = _rnd(comp[rule["method"]], 4)
        else:
            prior = static_attrition_baseline(ctx, spec["path"]) if isinstance(rule, dict) and "relative_to_control" in rule else None
            out[name] = _rnd(_baseline_value(rule, prior), 4)
    return out


def evaluate(ctx: InstanceContext, scenario_ids: list[str]) -> dict[str, Any]:
    """Score the baseline prediction against reference outcomes and compare what-if scenarios. Writes runs/<id>/evaluation.json."""
    from ..scenarios.loader import load_scenario
    proto = ctx.yaml("evaluation/protocol.yaml")
    ref_path = ctx.root / str(proto.get("reference", "data/normalized/reference_outcomes.json"))
    ref = json.loads(ref_path.read_text()) if ref_path.exists() else {}
    arms = {str(k): str(v) for k, v in (proto.get("arms") or {"0": "Office-only", "1": "Offered hybrid work"}).items()}
    eval_sid = str(proto.get("scenario", "evaluation"))
    seeds_cfg = proto.get("seeds") or {"start": 1, "count": 20}
    seeds = list(seeds_cfg) if isinstance(seeds_cfg, list) else list(range(int(seeds_cfg.get("start", 1)), int(seeds_cfg.get("start", 1)) + int(seeds_cfg.get("count", 20))))
    base_scn = _merge(load_scenario(ctx, eval_sid), proto.get("overrides") or {})

    per_seed: list[dict[str, Any]] = []
    for sd in seeds:
        per_seed.append(_run_once(ctx, base_scn, int(sd)))

    # ---- metrics ----
    metrics_out, headline = [], {}
    seed_table: list[dict[str, Any]] = [{"seed": int(sd)} for sd in seeds]
    for spec in proto.get("metrics") or []:
        sims = [_value(m, spec) for m in per_seed]
        vals = [v for v in sims if v is not None]
        for row, v in zip(seed_table, sims):
            row[spec["id"]] = _rnd(v, 4)
        ref_node = _dig(ref, spec.get("actual_path", spec["path"]))
        actual = _fnum(ref_node.get(str(spec.get("field", "itt")))) if isinstance(ref_node, dict) else None
        fld = str(spec.get("field", "itt"))
        actual_se = _fnum((ref_node.get("se") or {}).get(fld)) if isinstance(ref_node, dict) and isinstance(ref_node.get("se"), dict) else None
        lo, hi = interval(vals) if vals else (None, None)
        # Ensemble expectation is the point prediction; realized draws give the
        # predictive interval. Do not independently median arms and their effect.
        point_spec = {**spec, "path": spec.get("point_path", spec["path"])}
        sim_med = _mean([_value(m, point_spec) for m in per_seed])
        baselines = comparison_values(ctx, spec)
        entry = {"id": spec["id"], "label": spec.get("label", spec["id"]), "simulated": _rnd(sim_med, 4), "simulated_mean": _rnd(_mean(vals), 4),
                 "actual": _rnd(actual, 4), "baseline": baselines.get("zero_effect", next(iter(baselines.values()), None)) if baselines else None,
                 "baselines": baselines, "unit": spec.get("unit", ""), "better": spec.get("better", "lower"),
                 "interval": [_rnd(lo, 4), _rnd(hi, 4)], "n_seeds": len(vals), "primary": bool(spec.get("primary", False)), "actual_se": _rnd(actual_se, 4)}
        if actual is not None and sim_med is not None:
            entry["error"] = _rnd(sim_med - actual, 4)
            if actual_se:
                entry["trial_ci95"] = [_rnd(actual - 1.96 * actual_se, 4), _rnd(actual + 1.96 * actual_se, 4)]
                entry["within_trial_ci95"] = bool(actual - 1.96 * actual_se <= sim_med <= actual + 1.96 * actual_se)
            entry["abs_error"] = _rnd(abs(sim_med - actual), 4)
            entry["covered_90"] = bool(coverage(vals, actual)) if vals else None
            entry["sign_correct"] = bool(np.sign(sim_med) == np.sign(actual)) if actual != 0 else None
            entry["baseline_errors"] = {k: _rnd(abs(v - actual), 4) for k, v in baselines.items() if v is not None}
        metrics_out.append(entry)
        if spec.get("primary"):
            headline[spec["id"]] = {k: entry.get(k) for k in ("label", "simulated", "actual", "baseline", "unit", "better", "interval", "covered_90", "within_trial_ci95", "error")}

    # ---- what-if scenarios ----
    wi = proto.get("whatif") or {}
    whatif_ids = [s for s in (wi.get("scenarios") or []) if s in scenario_ids or not scenario_ids] or list(wi.get("scenarios") or [])
    wseeds = [int(s) for s in (wi.get("seeds") or [1])]
    comparison: list[dict[str, Any]] = []

    def kpis(runs: list[dict[str, Any]], sid: str, title: str, n_seeds: int) -> dict[str, Any]:
        def avg(path: str, field: str, nd: int = 2) -> float | None:
            return _rnd(_mean([_fnum((_dig(m, path) or {}).get(field)) for m in runs]), nd)
        ap = "expected_attrition_pct" if all("expected_attrition_pct" in m for m in runs) else "attrition_pct"
        row = {"scenario": sid, "title": title, "seeds": n_seeds, "attrition_basis": "hazard-implied expectation" if ap.startswith("expected") else "realized",
               "attrition_pct_control": avg(f"{ap}.all", "0"), "attrition_pct_treatment": avg(f"{ap}.all", "1"),
               "attrition_pct_all": _rnd(_mean([(m["expected_quits_total"] if ap.startswith("expected") else sum(m["quits"].values())) * 100.0 / m["headcount"] for m in runs]), 2),
               "attrition_itt_pp": avg(f"{ap}.all", "itt"),
               "attrition_pct_managers_control": avg(f"{ap}.by.managerial.1", "0"), "attrition_pct_managers_treatment": avg(f"{ap}.by.managerial.1", "1"),
               "attrition_pct_nonmanagers_control": avg(f"{ap}.by.managerial.0", "0"), "attrition_pct_nonmanagers_treatment": avg(f"{ap}.by.managerial.0", "1"),
               "realized_attrition_pct_control": avg("attrition_pct.all", "0"), "realized_attrition_pct_treatment": avg("attrition_pct.all", "1"),
               "realized_attrition_pct_all": _rnd(_mean([100.0 * sum(m["quits"].values()) / m["headcount"] for m in runs]), 2),
               "satisfaction_control": avg("satisfaction.work_satisfaction", "0"), "satisfaction_treatment": avg("satisfaction.work_satisfaction", "1"),
               "work_life_balance_control": avg("satisfaction.work_life_balance", "0"), "work_life_balance_treatment": avg("satisfaction.work_life_balance", "1"),
               "take_up_control": avg("takeup.mean_by_arm", "0", 3), "take_up_treatment": avg("takeup.mean_by_arm", "1", 3),
               "performance_control": avg("performance.2021H2", "0", 3), "performance_treatment": avg("performance.2021H2", "1", 3)}
        for k in ("performance_control", "performance_treatment"):
            if row[k] is None and runs and runs[0].get("performance"):
                pid = next(iter(runs[0]["performance"]))
                row[k] = avg(f"performance.{pid}", "0" if k.endswith("control") else "1", 3)
        row["quits_total"] = _rnd(_mean([m.get("expected_quits_total", sum(m["quits"].values())) for m in runs]), 1)
        row["realized_quits_total"] = _rnd(_mean([sum(m["quits"].values()) for m in runs]), 1)
        return row

    base_title = str(load_scenario(ctx, "baseline").get("title", "baseline")) if (ctx.scenarios_dir / "baseline.yaml").exists() else eval_sid
    matched_base = [m for m, sd in zip(per_seed, seeds) if sd in wseeds]
    if len(matched_base) != len(wseeds):
        raise ValueError("Alternative seeds must be a subset of evaluation seeds")
    comparison.append(kpis(per_seed, "baseline", base_title, len(per_seed)))
    whatif_runs: dict[str, list[dict[str, Any]]] = {}
    for sid in whatif_ids:
        try:
            scn = _merge(load_scenario(ctx, sid), wi.get("overrides") or {})
        except FileNotFoundError:
            continue
        runs = [_run_once(ctx, scn, sd) for sd in wseeds]
        whatif_runs[sid] = runs
        comparison.append(kpis(runs, sid, str(scn.get("title", sid)), len(runs)))
    paired_comparison = [kpis(matched_base, "baseline", base_title, len(matched_base)), *comparison[1:]]
    paired_effects = {}
    for sid, runs in whatif_runs.items():
        diffs = [(a["expected_quits_total"] - b["expected_quits_total"]) * 100 / b["headcount"] for b, a in zip(matched_base, runs)]
        paired_effects[sid] = {"attrition_pp": _mean(diffs), "interval": list(interval(diffs)), "seeds": wseeds}

    charts = _charts(per_seed, ref, arms, paired_comparison, metrics_out)
    out = {"instance": ctx.id, "generated": datetime.now(timezone.utc).isoformat(), "scenarios": ["baseline", *whatif_runs.keys()],
           "protocol": {"design": proto.get("design", ""), "t0": proto.get("t0"), "horizon_days": proto.get("horizon_days"), "seeds": len(per_seed),
                        "whatif_seeds": len(wseeds), "evaluation_scenario": eval_sid, "freeze_rule": ctx.meta.get("evaluation", {}).get("freeze_rule", "")},
           "headline": headline, "metrics": metrics_out, "charts": charts, "scenario_comparison": comparison,
           "paired_comparison": paired_comparison, "paired_effects": paired_effects,
           "run_ids": {"evaluation": [m["run_id"] for m in per_seed], **{sid: [m["run_id"] for m in runs] for sid, runs in whatif_runs.items()}},
           "seeds": seed_table, "priors": {k: {"central": v.get("central"), "range": v.get("range"), "source": v.get("source")} for k, v in (ctx.yaml("calibration/priors.yaml").get("parameters") or {}).items()},
           "reference_source": ref.get("source", ""), "comparators": attrition_comparators(ctx)}
    (RUNS_DIR / ctx.id).mkdir(parents=True, exist_ok=True)
    target = RUNS_DIR / ctx.id / "evaluation.json"
    target.write_text(json.dumps(out, indent=1, default=str))
    return out


def _series_stats(per_seed: list[dict[str, Any]], getter: Any) -> tuple[list[float | None], list[float | None], list[float | None]]:
    arrs = [np.array([np.nan if v is None else v for v in getter(m)], dtype=float) for m in per_seed]
    L = min(len(a) for a in arrs) if arrs else 0
    if L == 0:
        return [], [], []
    stack = np.vstack([a[:L] for a in arrs])
    med = np.nanmean(stack, axis=0); lo = np.nanquantile(stack, 0.05, axis=0); hi = np.nanquantile(stack, 0.95, axis=0)
    f = lambda a: [_rnd(x, 3) for x in a]
    return f(med), f(lo), f(hi)


def _charts(per_seed: list[dict[str, Any]], ref: dict[str, Any], arms: dict[str, str], comparison: list[dict[str, Any]], metrics_out: list[dict[str, Any]]) -> list[dict[str, Any]]:
    charts: list[dict[str, Any]] = []
    labels = [arms[a] for a in sorted(arms)]
    def sim_level(path: str, field: str) -> float | None:
        return _rnd(_mean([_fnum((_dig(m, path) or {}).get(field)) for m in per_seed]), 3)
    def ref_level(path: str, field: str) -> float | None:
        return _rnd((_dig(ref, path) or {}).get(field), 3)
    def iv(path: str, field: str) -> list[float | None]:
        vals = [_fnum((_dig(m, path) or {}).get(field)) for m in per_seed]
        vals = [v for v in vals if v is not None]
        lo, hi = interval(vals) if vals else (None, None)
        return [_rnd(lo, 3), _rnd(hi, 3)]
    # 1. attrition by group
    charts.append({"id": "attrition_by_arm", "type": "bar", "title": "Six-month attrition by group: simulated vs actual", "x_label": "", "y_label": "% of employees who left",
                   "x": labels, "series": [{"name": "Simulation prediction (average across runs)", "y": [sim_level("attrition_pct.all", a) for a in sorted(arms)], "interval": [iv("attrition_pct.all", a) for a in sorted(arms)]},
                                           {"name": "Actual outcome", "y": [ref_level("attrition_pct.all", a) for a in sorted(arms)]}],
                   "note": "Simulation predictions are means across simulation runs with 90% predictive intervals; both employee groups are evaluation-only."})
    # 2. satisfaction by group (scales)
    scales = [s for s in ("work_satisfaction", "work_life_balance", "life_satisfaction", "recommend_friends") if s in (ref.get("satisfaction") or {}) or any(s in (m.get("satisfaction") or {}) for m in per_seed)]
    charts.append({"id": "satisfaction_by_arm", "type": "bar", "title": "End-of-period survey scales by group (0-10)", "x_label": "", "y_label": "mean score",
                   "x": [f"{s.replace('_', ' ')} / {arms[a]}" for s in scales for a in sorted(arms)],
                   "series": [{"name": "Simulation prediction", "y": [sim_level(f"satisfaction.{s}", a) for s in scales for a in sorted(arms)]},
                              {"name": "Actual outcome", "y": [ref_level(f"satisfaction.{s}", a) for s in scales for a in sorted(arms)]}],
                   "note": "Offered hybrid work-minus-control gaps are the scored quantity; levels depend on the satisfaction anchor prior."})
    # 3. managers vs non-managers
    charts.append({"id": "manager_contrast", "type": "bar", "title": "Attrition by role and arm: simulated vs actual", "x_label": "", "y_label": "% who left",
                   "x": [f"Non-managers / {arms[a]}" for a in sorted(arms)] + [f"Managers / {arms[a]}" for a in sorted(arms)],
                   "series": [{"name": "Simulation prediction", "y": [sim_level("attrition_pct.by.managerial.0", a) for a in sorted(arms)] + [sim_level("attrition_pct.by.managerial.1", a) for a in sorted(arms)],
                               "interval": [iv("attrition_pct.by.managerial.0", a) for a in sorted(arms)] + [iv("attrition_pct.by.managerial.1", a) for a in sorted(arms)]},
                              {"name": "Actual outcome", "y": [ref_level("attrition_pct.by.managerial.0", a) for a in sorted(arms)] + [ref_level("attrition_pct.by.managerial.1", a) for a in sorted(arms)]}],
                   "note": "The effect concentrates among non-managers in both the prediction and the experiment."})
    # 4. cumulative attrition curves with band
    weeks = per_seed[0]["cumulative_attrition_pct"]["weeks"] if per_seed else []
    series = []
    for a in sorted(arms):
        med, lo, hi = _series_stats(per_seed, lambda m, a=a: m["cumulative_attrition_pct"][a])
        series.append({"name": f"{arms[a]} (simulated mean)", "y": med, "band": [lo, hi]})
    for a in sorted(arms):
        act = ref_level("attrition_pct.all", a)
        series.append({"name": f"{arms[a]} actual endpoint", "y": [None] * (len(weeks) - 1) + [act] if weeks else [], "point": True})
    charts.append({"id": "cumulative_attrition", "type": "line", "title": "Cumulative attrition by group over the experiment (weekly)", "x_label": "week ending", "y_label": "% who left",
                   "x": weeks, "series": series, "note": "Bands are 5th-95th percentiles across simulation runs. Actual experiment endpoints shown at the final week."})
    # 5. take-up over time
    tdates = per_seed[0]["takeup"]["dates"] if per_seed else []
    tser = []
    for a in sorted(arms):
        if all(a in m["takeup"]["by_arm"] for m in per_seed) and tdates:
            med, lo, hi = _series_stats(per_seed, lambda m, a=a: m["takeup"]["by_arm"][a])
            tser.append({"name": f"{arms[a]} simulated", "y": med, "band": [lo, hi]})
    rt = ref.get("takeup") or {}
    if rt.get("dates") and tdates:
        pos = {d: i for i, d in enumerate(rt["dates"])}
        for a in sorted(arms):
            ys = rt.get("by_arm_weighted", {}).get(a)
            if ys:
                tser.append({"name": f"{arms[a]} actual", "y": [(_rnd(ys[pos[d]], 3) if d in pos else None) for d in tdates]})
    charts.append({"id": "takeup_series", "type": "line", "title": "Share of eligible WFH days taken, by group", "x_label": "eligible day", "y_label": "share working from home",
                   "x": tdates, "series": tser, "note": "Actual series is the deposit's group-level take-up (volunteer groups weighted by their population share). Volunteers became eligible on 13 Sep 2021."})
    # 6. scenario bars
    scn = [c for c in comparison]
    charts.append({"id": "scenario_bars", "type": "bar", "title": "Policy variants: attrition by group", "x_label": "", "y_label": "% who left",
                   "x": [c["title"] for c in scn],
                   "series": [{"name": arms.get("0", "Office-only"), "y": [c["attrition_pct_control"] for c in scn]}, {"name": arms.get("1", "Offered hybrid work"), "y": [c["attrition_pct_treatment"] for c in scn]},
                              {"name": "Whole workforce", "y": [c["attrition_pct_all"] for c in scn]}],
                   "note": "Expected attrition estimated from accumulated risk while employees remain active, averaged across matching simulation runs. Uncertainty remains in simulated work and exit paths. In 'hybrid for all' both arms receive the offer."})
    charts.append({"id": "scenario_satisfaction", "type": "bar", "title": "Policy variants: endline work satisfaction and take-up", "x_label": "", "y_label": "score / share",
                   "x": [c["title"] for c in scn],
                   "series": [{"name": f"Satisfaction {arms.get('0', 'Office-only')}", "y": [c["satisfaction_control"] for c in scn]}, {"name": f"Satisfaction {arms.get('1', 'Offered hybrid work')}", "y": [c["satisfaction_treatment"] for c in scn]},
                              {"name": f"Take-up {arms.get('1', 'Offered hybrid work')} (x10)", "y": [None if c["take_up_treatment"] is None else round(10 * c["take_up_treatment"], 2) for c in scn]}],
                   "note": ""})
    # 7. ITT prediction distribution vs actual for primary metrics
    prim = [m for m in metrics_out if m.get("primary")]
    charts.append({"id": "itt_forecast_vs_actual", "type": "bar", "title": "Offered hybrid work effects: prediction (mean, 90% interval) vs experiment", "x_label": "", "y_label": "effect (pp or points)",
                   "x": [m["label"] for m in prim],
                   "series": [{"name": "Simulation prediction", "y": [m["simulated"] for m in prim], "interval": [m["interval"] for m in prim]}, {"name": "Actual outcome", "y": [m["actual"] for m in prim]},
                              {"name": "Zero-effect baseline", "y": [m["baselines"].get("zero_effect") for m in prim]}],
                   "note": "Retrospective comparison: employee information from before the policy and assumptions from earlier research drive the simulation; neither arm is used for calibration."})
    return charts


# ----------------------------------------------------------------------------- results view (Results tab)

def results_view(ctx: InstanceContext) -> dict[str, Any]:
    """Actual outcome, baseline prediction and the alternative scenario side by side. Levels are whole-workforce where the
    alternative removes the treatment/control contrast; the treatment-effect validation keeps the arm contrast."""
    from ..evaluation.results import base_document, dig, interval_of, mean_of, run_docs, series_mean
    doc = base_document(ctx)
    ev_path = ctx.runs_dir / "evaluation.json"
    ev = json.loads(ev_path.read_text()) if ev_path.exists() else {}
    proto = ctx.yaml("evaluation/protocol.yaml")
    ref_path = ctx.root / str(proto.get("reference", "data/normalized/reference_outcomes.json"))
    ref = json.loads(ref_path.read_text()) if ref_path.exists() else {}
    arms = {str(k): str(v) for k, v in (proto.get("arms") or {"0": "Office-only", "1": "Offered hybrid work"}).items()}
    base = doc["scenarios"]["baseline"]; alt = doc["scenarios"].get("alternative")
    evm = {m["id"]: m for m in ev.get("metrics", [])}
    cmp_rows = {r["scenario"]: r for r in ev.get("scenario_comparison", [])}
    from ..scenarios import load_scenario
    try:
        pol = (load_scenario(ctx, base["id"]).get("world") or {}).get("policy") or {}
    except FileNotFoundError:
        pol = {}
    days = [str(d) for d in (pol.get("days") or [])]
    day_text = " and ".join(days) if len(days) <= 2 else ", ".join(days[:-1]) + " and " + days[-1]
    n_ctrl = int(dig(ref, "attrition_pct.all.n.0") or 0); n_trt = int(dig(ref, "attrition_pct.all.n.1") or 0)
    group = {"0": f"Office-only group · {n_ctrl:,} employees", "1": f"Offered hybrid work · {n_trt:,} employees"}
    group_short = {"0": "Office-only", "1": "Offered hybrid work"}
    doc["design"] = (f"Trip.com randomly assigned {n_trt:,} employees to an offer of {day_text} at home and {n_ctrl:,} to office-only work. "
                     "Actual outcomes come from the following six months. Comparing the two groups during the same period measures the impact of the offer; "
                     "the earlier six-month attrition rate provides historical context.")

    # ---- sources
    sources = [{"id": "actual", "label": f"{base['title']} · actual outcome outcome", "kind": "actual", "scenario": base["id"], "note": f"Outcomes of the real experiment ({ref.get('source', 'reference outcomes')})."},
               {"id": "baseline", "label": f"{base['title']} · simulation prediction", "kind": "simulated", "scenario": base["id"], "runs": (ev.get("protocol") or {}).get("seeds"),
                "note": f"Mean prediction over {(ev.get('protocol') or {}).get('seeds', '?')} seeds; 90% predictive interval across simulation runs. Retrospective evaluation using pretreatment inputs; both employee groups are scoring-only."}]
    alt_metrics = run_docs(ctx, alt["id"], "metrics", ev.get("run_ids", {}).get(alt["id"], [])) if alt else []
    if alt:
        sources.append({"id": "alternative", "label": f"{alt['title']} · simulation prediction", "kind": "simulated", "scenario": alt["id"], "runs": len(alt_metrics),
                        "note": f"Mean over {len(alt_metrics)} completed runs of the alternative scenario (5%-95% range across runs)."})

    # ---- level metrics (whole workforce; arms where they mean something)
    n0 = float(dig(ref, "attrition_pct.all.n.0") or 820); n1 = float(dig(ref, "attrition_pct.all.n.1") or 792)
    def wmean(a: float | None, b: float | None) -> float | None:
        return round((a * n0 + b * n1) / (n0 + n1), 3) if a is not None and b is not None else None
    def arm_level(docs: list[dict[str, Any]], path: str, nd: int = 3):
        a, b = mean_of(docs, f"{path}.0", nd), mean_of(docs, f"{path}.1", nd)
        return wmean(a, b), a, b
    base_row = cmp_rows.get("baseline", {})
    metrics: list[dict[str, Any]] = []
    def add(mid: str, label: str, unit: str, better: str, actual, base_v, alt_v, base_iv=None, alt_iv=None, note: str = "") -> None:
        metrics.append({"id": mid, "label": label, "unit": unit, "better": better, "values": {"actual": actual, "baseline": base_v, "alternative": alt_v},
                        "intervals": {k: v for k, v in (("baseline", base_iv), ("alternative", alt_iv)) if v}, "note": note})
    # attrition, whole workforce: hazard-implied expectation for simulated sources (same basis as the scenario comparison)
    act_all = wmean(dig(ref, "attrition_pct.all.0"), dig(ref, "attrition_pct.all.1"))
    alt_all = mean_of(alt_metrics, "expected_attrition_pct.all.0") if alt_metrics else None
    alt_all_w = None
    if alt_metrics:
        a, b = mean_of(alt_metrics, "expected_attrition_pct.all.0"), mean_of(alt_metrics, "expected_attrition_pct.all.1"); alt_all_w = wmean(a, b)
    add("attrition_all", "Six-month attrition, whole workforce", "%", "lower", act_all, base_row.get("attrition_pct_all"), alt_all_w,
        note="Simulated values are the hazard-implied expectation (average across runs), the same basis as the scenario comparison.")
    add("attrition_control", f"Attrition, {group_short['0']}", "%", "lower", dig(ref, "attrition_pct.all.0"), (evm.get("attrition_control_pct") or {}).get("simulated"),
        mean_of(alt_metrics, "expected_attrition_pct.all.0"), (evm.get("attrition_control_pct") or {}).get("interval"), interval_of(alt_metrics, "expected_attrition_pct.all.0"),
        note="For the alternative everyone is offered the policy, so the two groups only differ by birthday.")
    add("attrition_treatment", f"Attrition, {group_short['1']}", "%", "lower", dig(ref, "attrition_pct.all.1"), (evm.get("attrition_treatment_pct") or {}).get("simulated"),
        mean_of(alt_metrics, "expected_attrition_pct.all.1"), (evm.get("attrition_treatment_pct") or {}).get("interval"), interval_of(alt_metrics, "expected_attrition_pct.all.1"))
    sat_act = wmean(dig(ref, "satisfaction.work_satisfaction.0"), dig(ref, "satisfaction.work_satisfaction.1"))
    add("work_satisfaction", "End-of-period work satisfaction (0-10), whole workforce", "points", "higher", sat_act, wmean(base_row.get("satisfaction_control"), base_row.get("satisfaction_treatment")),
        arm_level(alt_metrics, "satisfaction.work_satisfaction")[0] if alt_metrics else None,
        note="Starting satisfaction is estimated from earlier research. The overall score and the difference between groups are shown separately.")
    wlb_act = wmean(dig(ref, "satisfaction.work_life_balance.0"), dig(ref, "satisfaction.work_life_balance.1"))
    add("work_life_balance", "End-of-period work-life balance (0-10), whole workforce", "points", "higher", wlb_act, wmean(base_row.get("work_life_balance_control"), base_row.get("work_life_balance_treatment")),
        arm_level(alt_metrics, "satisfaction.work_life_balance")[0] if alt_metrics else None)
    add("take_up", "Share of eligible WFH days taken (offered employees)", "share", "higher", dig(ref, "takeup.window_means_by_arm.1"), (evm.get("takeup_treatment") or {}).get("simulated"),
        wmean(mean_of(alt_metrics, "takeup.window_means_by_arm.0"), mean_of(alt_metrics, "takeup.window_means_by_arm.1")) if alt_metrics else None,
        (evm.get("takeup_treatment") or {}).get("interval"), None, note=f"Actual outcome and prediction: the {arms['1'].lower()} group; alternative: everyone is offered.")
    perf_act = wmean(dig(ref, "performance.2021H2.0"), dig(ref, "performance.2021H2.1"))
    add("performance", "Performance grade 2021H2 (1-5), whole workforce", "points", "higher", perf_act, wmean(base_row.get("performance_control"), base_row.get("performance_treatment")),
        arm_level(alt_metrics, "performance.2021H2")[0] if alt_metrics else None)

    paired_seeds = set(next(iter(ev.get("paired_effects", {}).values()), {}).get("seeds", []))
    paired_metrics = [m for m in run_docs(ctx, "evaluation", "metrics", ev.get("run_ids", {}).get("evaluation", [])) if m.get("seed") in paired_seeds]
    paired_rows = {r["scenario"]: r for r in ev.get("paired_comparison", [])}
    paired_base = paired_rows.get("baseline", base_row)
    pair_values = {"attrition_all": paired_base.get("attrition_pct_all"),
                   "attrition_control": paired_base.get("attrition_pct_control"), "attrition_treatment": paired_base.get("attrition_pct_treatment"),
                   "work_satisfaction": wmean(paired_base.get("satisfaction_control"), paired_base.get("satisfaction_treatment")),
                   "work_life_balance": wmean(paired_base.get("work_life_balance_control"), paired_base.get("work_life_balance_treatment")),
                   "performance": wmean(paired_base.get("performance_control"), paired_base.get("performance_treatment")),
                   "take_up": mean_of(paired_metrics, "takeup.window_means_by_arm.1")}
    for metric in metrics:
        metric["paired_baseline"] = pair_values.get(metric["id"])

    # ---- treatment-effect validation (the scored prediction)
    effects = []
    for mid, m in (ev.get("headline") or {}).items():
        effects.append({**m, "id": mid, "trial_ci95": (evm.get(mid) or {}).get("trial_ci95"), "actual_se": (evm.get(mid) or {}).get("actual_se")})

    # ---- trajectories: cumulative attrition and take-up, one series per source
    charts: list[dict[str, Any]] = []
    evc = {c["id"]: c for c in ev.get("charts", [])}
    cum = evc.get("cumulative_attrition")
    if cum:
        series = []
        for s in cum.get("series", []):
            arm_key = next((k for k, v in arms.items() if s["name"].startswith(v)), "0")
            if s.get("band"):
                py, plo, phi = series_mean(paired_metrics, lambda d, k=arm_key: d["cumulative_attrition_pct"][k])
                series.append({"name": f"{group_short[arm_key]} · simulation prediction", "y": s["y"], "band": s["band"], "paired_y": py, "paired_band": [plo, phi], "source": "baseline", "arm": arms[arm_key]})
            elif s.get("point"):
                series.append({"name": f"{group_short[arm_key]} · actual outcome", "y": s["y"], "point": True, "source": "actual", "arm": arms[arm_key]})
        if alt_metrics:
            for arm_key, arm_label in arms.items():
                med, lo, hi = series_mean(alt_metrics, lambda d, k=arm_key: d["cumulative_attrition_pct"][k])
                if med:
                    series.append({"name": f"{group_short[arm_key]} · {alt['short_title']}", "y": med, "band": [lo, hi], "source": "alternative", "arm": arm_label})
        charts.append({"id": "cumulative_attrition", "type": "line", "title": "Cumulative attrition over the experiment (weekly, % who left)", "x": cum["x"], "x_label": cum.get("x_label", "week ending"), "y_label": "% who left", "series": series, "kind": "trajectory",
                       "note": "Bands: 5th-95th percentile across simulation runs. Actual outcome is the endpoint of the experiment (no weekly series in the deposit)."})
    tk = evc.get("takeup_series")
    if tk:
        series = []
        for s in tk.get("series", []):
            if not s["name"].startswith(arms["1"]):
                continue
            if s.get("band"):
                py, plo, phi = series_mean(paired_metrics, lambda d: d["takeup"]["by_arm"]["1"])
                series.append({"name": f"{group_short['1']} · simulation prediction", "y": s["y"], "band": s["band"], "paired_y": py, "paired_band": [plo, phi], "source": "baseline"})
            else:
                series.append({"name": f"{group_short['1']} · actual outcome", "y": s["y"], "source": "actual", "dashed": True})
        if alt_metrics:
            for arm_key, arm_label in arms.items():
                med, lo, hi = series_mean(alt_metrics, lambda d, k=arm_key: d["takeup"]["by_arm"][k])
                if med:
                    series.append({"name": f"{group_short[arm_key]} · {alt['short_title']}", "y": med, "band": [lo, hi], "source": "alternative"})
        charts.append({"id": "takeup_series", "type": "line", "title": "Share of eligible WFH days taken", "x": tk["x"], "x_label": "eligible day", "y_label": "share working from home", "series": series, "kind": "trajectory", "y_max": 1})
    sat = evc.get("satisfaction_by_arm")
    if sat:
        series = [{"name": "Simulation prediction", "y": sat["series"][0]["y"], "source": "baseline"}, {"name": "Actual outcome", "y": sat["series"][1]["y"], "source": "actual"}]
        if alt_metrics:
            ys = []
            paired_ys = []
            for lab in sat["x"]:
                scale, arm = lab.split(" / "); key = scale.lower().replace(" ", "_")
                arm_key = next((k for k, v in arms.items() if v == arm), "0")
                ys.append(mean_of(alt_metrics, f"satisfaction.{key}.{arm_key}") if key else None)
                paired_ys.append(mean_of(paired_metrics, f"satisfaction.{key}.{arm_key}") if key else None)
            series[0]["paired_y"] = paired_ys
            series.append({"name": alt["short_title"], "y": ys, "source": "alternative"})
        charts.append({"id": "satisfaction_by_arm", "type": "bar", "title": "End-of-period survey scales by group (0-10)", "x": [x.replace(f"/ {arms['0']}", f"/ {group_short['0']}").replace(f"/ {arms['1']}", f"/ {group_short['1']}") for x in sat["x"]], "x_label": "", "y_label": sat.get("y_label", "mean score"), "series": series, "kind": "bars", "y_min": 5, "y_max": 10})

    kind_labels = {"actual": "Actual outcome (actual data)", "baseline": "Simulation prediction", "alternative": "Alternative simulation prediction"}
    shorts = {"actual": "Actual outcome", "baseline": "Simulation prediction", "alternative": alt["short_title"] if alt else "Alternative"}
    for src in sources:
        src["kind_label"] = kind_labels.get(src["id"], src["kind"]); src["short"] = shorts.get(src["id"], src["id"])
    # hero: the one result an investor should read first, every number computed above
    att = (ev.get("headline") or {}).get("attrition_itt_pp") or {}
    n_ci = sum(1 for e in effects if e.get("within_trial_ci95")); n_eff = sum(1 for e in effects if e.get("within_trial_ci95") is not None)
    base_all = paired_base.get("attrition_pct_all"); alt_quits = mean_of(alt_metrics, "expected_quits_total", 1) if alt_metrics else None
    saved = (paired_base.get("quits_total") - alt_quits) if (alt_quits is not None and paired_base.get("quits_total") is not None) else None
    def arm_level_actual(path: str, k: str):
        return dig(ref, f"{path}.{k}")
    story_metrics = [
        {"id": "attrition", "label": "Six-month attrition", "unit": "%", "better": "lower", "before_actual": dig(ref, "attrition_pct.all.0"), "before_sim": (evm.get("attrition_control_pct") or {}).get("simulated"),
         "after_actual": dig(ref, "attrition_pct.all.1"), "after_sim": (evm.get("attrition_treatment_pct") or {}).get("simulated"),
         "intervals": {"before_sim": (evm.get("attrition_control_pct") or {}).get("interval"), "after_sim": (evm.get("attrition_treatment_pct") or {}).get("interval")}},
        {"id": "work_satisfaction", "label": "End-of-period work satisfaction (0-10)", "unit": "points", "better": "higher", "before_actual": arm_level_actual("satisfaction.work_satisfaction", "0"), "before_sim": base_row.get("satisfaction_control"), "after_actual": arm_level_actual("satisfaction.work_satisfaction", "1"), "after_sim": base_row.get("satisfaction_treatment"), "intervals": {},
         "note": "Starting satisfaction is estimated from earlier research. The overall score and the difference between groups are shown separately."},
        {"id": "work_life_balance", "label": "End-of-period work-life balance (0-10)", "unit": "points", "better": "higher", "before_actual": arm_level_actual("satisfaction.work_life_balance", "0"), "before_sim": base_row.get("work_life_balance_control"), "after_actual": arm_level_actual("satisfaction.work_life_balance", "1"), "after_sim": base_row.get("work_life_balance_treatment"), "intervals": {}},
        {"id": "take_up", "label": "Share of eligible home days taken", "unit": "share", "better": "higher", "before_actual": dig(ref, "takeup.window_means_by_arm.0"), "before_sim": base_row.get("take_up_control"), "after_actual": dig(ref, "takeup.window_means_by_arm.1"), "after_sim": (evm.get("takeup_treatment") or {}).get("simulated"), "intervals": {"after_sim": (evm.get("takeup_treatment") or {}).get("interval")}},
        {"id": "performance", "label": "Performance grade 2021H2 (1-5)", "unit": "points", "better": "higher", "before_actual": arm_level_actual("performance.2021H2", "0"), "before_sim": base_row.get("performance_control"), "after_actual": arm_level_actual("performance.2021H2", "1"), "after_sim": base_row.get("performance_treatment"), "intervals": {}},
    ]
    for m, mid in (("attrition", "attrition_itt_pp"), ("work_satisfaction", "work_satisfaction_itt"), ("work_life_balance", "work_life_balance_itt"), ("performance", "performance_2021H2_itt")):
        for sm in story_metrics:
            if sm["id"] == m and (evm.get(mid) or {}).get("simulated") is not None:
                sm["engine_effect"] = (evm.get(mid) or {}).get("simulated")
                sm["effect_label"] = (evm.get(mid) or {}).get("label")
    comp = attrition_comparators(ctx)
    baselines = [
        {"id": "no_effect", "label": "No change", "values": {m["id"]: 0.0 for m in story_metrics if m["id"] != "take_up"}},
        {"id": "proportional_days", "label": comp["method"]["label"], "values": {"attrition": comp["proportional_days_effect_pp"]}},
    ]
    population = pd.read_parquet(ctx.data_normalized / "population.parquet")
    for m in story_metrics:
        m["reference_actual"] = m["before_actual"]
        m["before_actual"] = float(population.prior_performance.mean()) if m["id"] == "performance" else None
        if m["id"] == "attrition":
            m["before_actual"] = comp["no_change_pct"]
            m["note"] = "Before: published aggregate for the Airfare and IT divisions. After: employees offered hybrid work. The office-only group is compared separately below."
        m.pop("before_sim", None)
    doc["story"] = {"before": {"label": "Before the policy", "sublabel": "Airfare and IT divisions · preceding six months · published aggregate",
                               "stats": [{"label": "Six-month attrition", "value": comp["no_change_pct"], "unit": "%"}, {"label": "Employees in the later experiment", "value": len(population)}]},
                    "change": {"label": f"Offered {day_text} at home", "description": "The change was given to half the employees, chosen by birthday, while the other half kept working in the office. Both groups' outcomes are scored after the policy change.",
                               "stats": [{"label": "Employees offered", "value": f"{n_trt:,} of {n_ctrl + n_trt:,}"}, {"label": "Home days", "value": day_text}]},
                    "after": {"label": "With the change", "sublabel": group["1"]},
                    "columns": {"before_actual": "Actual outcome", "after_actual": "Actual outcome", "after_sim": "Simulation prediction"},
                    "metrics": story_metrics, "chart": "cumulative_attrition", "baselines": baselines, "baseline_basis": "effect",
                    "comparator_explanation": {
                        "paragraphs": [f"No change carries the earlier {comp['no_change_pct']:.1f}% attrition rate forward and assumes the hybrid offer has no effect.",
                            f"The simple calculation uses an earlier Ctrip study of volunteer call-center employees: {comp['study']['home_days_per_week']} home days per week reduced attrition by about {100*comp['study']['relative_attrition_reduction']:.0f}% over {comp['study']['duration_months']} months. For {comp['home_days']} home days, it assumes {100*comp['relative_reduction']:.0f}% lower attrition. This proportional scaling is an assumption, and the jobs and period differ.",
                            "Only attrition has this second comparison. The earlier study does not supply directly comparable estimates for the other outcomes."],
                        "formula": f"{comp['no_change_pct']:.1f}% × (1 − {100*comp['study']['relative_attrition_reduction']:.0f}% × {comp['home_days']}/{comp['study']['home_days_per_week']}) = {comp['proportional_days_pct']:.2f}% predicted attrition; a change of {comp['proportional_days_effect_pp']:.2f} percentage points.",
                        "sources": [{"label": "Pre-policy attrition source", "url": comp['history']['source_url']}, {"label": "Earlier four-day study", "url": comp['study']['source_url']}]},
                    "level_comparison": {"label": "Six-month attrition", "unit": "%", "actual": story_metrics[0]["after_actual"], "simulated": story_metrics[0]["after_sim"],
                        "predictions": [{"label": "No change", "value": comp["no_change_pct"]}, {"label": comp["method"]["label"], "value": comp["proportional_days_pct"]}]},
                    "fidelity": [{"label": "Simulation prediction of the attrition change", "value": att.get("simulated"), "unit": "pp"},
                                 {"label": "Actual attrition change", "value": att.get("actual"), "unit": "pp"},
                                 {"label": "Absolute prediction error", "value": abs(att.get("error", 0)), "unit": "pp"}]}
    hero = {"kicker": "Simulation compared with the randomized experiment", "groups": group,
            "stats": [{"label": "Simulation prediction: attrition effect of two WFH days", "value": att.get("simulated"), "unit": "pp"},
                      {"label": "The randomized experiment measured", "value": att.get("actual"), "unit": "pp"},
                      {"label": "Predictions inside the experiment's 95% CI", "value": f"{n_ci} of {n_eff}", "unit": ""}],
            "claim": "The impact compares employees offered hybrid work with the office-only group during the same six months. Neither group's outcomes calibrate this simulation. These are retrospective comparisons; previous model choices had already been compared with the published results.",
            "chart": "cumulative_attrition"}
    if alt and alt_all_w is not None and base_all is not None:
        hero["alternative"] = {"kicker": f"Alternative: {alt['short_title']}", "stats": [{"label": "Six-month attrition, whole workforce", "value": f"{base_all:.1f}% → {alt_all_w:.1f}%", "unit": ""}] + ([{"label": "Fewer resignations among 1,612 employees", "value": round(saved), "unit": ""}] if saved is not None else []),
                               "text": f"Offering hybrid work to everyone takes six-month attrition from {base_all:.1f}% to {alt_all_w:.1f}%" + (f", about {saved:.0f} fewer resignations among {int(n0 + n1):,} employees." if saved is not None else ".")}
    doc.update({"sources": sources, "metrics": metrics, "effects": effects, "charts": charts, "hero": hero, "evaluation": {"generated": ev.get("generated"), "protocol": ev.get("protocol")}})
    return doc
