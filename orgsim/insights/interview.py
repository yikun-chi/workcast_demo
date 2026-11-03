"""Interview the agents of a run about the key metrics and extract topics, sentiment and insights.

Nothing here is measured on real people. Every interview is with a simulated agent, and every answer is rendered from
that agent's simulated record: its profile, trait layer, latent states and decisions (workforce worlds, from twins.json)
or its role pool's queue, utilization and exceptions (process worlds, from summary.json), or a company's simulated
tokens, model mix and spend (market worlds, from summary.json). Two voices:

  template   deterministic sentences built from the agent's numbers; always available, used for the demo
  llm        a hosted model writes the answers from the same facts (ANTHROPIC_API_KEY); topics and sentiment are still
             derived from the facts, so the extraction does not depend on the model

Output: runs/<id>/insights.json
  {generated, method, scenarios: {baseline: block, alternative: block}}
  block = {scenario, title, run_id, n_interviews, interviews: [{agent_id, role, group, outcome, facts, qa: [{metric,
           question, answer, topics, sentiment}]}], topics: [{id, label, count, share, by_group}], sentiment: {...},
           key_insights: [str]}
"""
from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

import numpy as np

from ..instances import InstanceContext
from ..scenarios import list_scenarios, scenario_roles
from ..store import RunReader, list_runs

TOPIC_LABELS = {
    # workforce
    "long_commute": "Long commute", "commute_saved": "Commute time saved on home days", "wfh_days_used": "Uses the home days",
    "option_unused": "Offered but rarely uses it", "not_offered_teammates_were": "Not offered while teammates were",
    "satisfaction_up": "Job satisfaction improved", "satisfaction_down": "Job satisfaction fell", "satisfaction_stable": "Job satisfaction unchanged",
    "work_life_balance_up": "Work-life balance improved", "family": "Family and children", "attachment_strong": "Strong attachment to the firm",
    "attachment_weak": "Weak attachment to the firm", "resigned": "Resigned during the period", "manager_role": "Manager: coordination and visibility",
    "performance_unchanged": "Output unchanged", "wants_more_days": "Would take more home days",
    # process
    "payment_run_cadence": "Payment-run cadence sets the clearing time", "payment_blocks": "Payment blocks hold invoices", "waiting_for_goods_receipt": "Waiting for the goods receipt",
    "capacity_slack": "Spare capacity in the role", "capacity_strain": "Role capacity under strain", "rework_exceptions": "Rework and exceptions",
    "hand_off_dependency": "Depends on another role's step", "vendor_timing": "Vendor invoice timing", "batch_automation": "Batch jobs do the routine steps",
    # market
    "growing": "Usage growing", "fading": "Usage fading", "one_off_job": "A one-off job, not a steady product", "steady_product": "A steady product with regular traffic",
    "price_up": "List prices went up", "price_down": "List prices went down", "switched_models": "Moved work to other models", "new_models": "Trying newly listed models",
    "coding_workload": "Coding workloads", "roleplay_workload": "Roleplay and creative workloads",
    "more_people_same_queue": "More people, same queue", "fewer_people_same_queue": "Fewer people, same queue", "throughput_up": "Throughput went up", "throughput_down": "Throughput went down",
    # adoption
    "adoption_up": "Adoption rising", "adoption_down": "Adoption falling", "adoption_flat": "Adoption flat", "imitation": "Following other adopters",
    "external_influence": "Steady outside pressure to adopt", "programme": "Adoption programme",
}


def _rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)


# ----------------------------------------------------------------------------- workforce interviews

WF_QUESTIONS = [
    ("attrition", "Did you think about leaving the company during these months? What weighed most?"),
    ("satisfaction", "How has your job satisfaction changed since August?"),
    ("work_life_balance", "What did the Wednesday-and-Friday arrangement mean for your week?"),
    ("performance", "Did it change how you got your work done?"),
]


def _wf_facts(tw: dict[str, Any], company: str) -> dict[str, Any]:
    tr, fs = tw.get("traits") or {}, tw.get("final_states") or {}
    prof = tw.get("profile") or ""
    elig, used = int(tw.get("eligible_days") or 0), int(tw.get("wfh_days") or 0)
    f = {"company": company, "role": tw.get("role"), "manager": tw.get("role") == "manager", "offered": bool(tw.get("offered")), "arm": tw.get("arm"),
         "commute_2way_h": float(tr.get("commute_2way_h") or 0.0), "eligible_days": elig, "wfh_days": used, "take_up": (used / elig) if elig else None,
         "sat_base": float(tr.get("sat_base") or 0.0), "sat_end": float(fs.get("job_satisfaction") or 0.0), "wlb_base": float(tr.get("wlb_base") or 0.0), "wlb_end": float(fs.get("work_life_balance") or 0.0),
         "relative_deprivation": float(fs.get("relative_deprivation") or 0.0), "attachment": float(fs.get("attachment") or 0.0), "quit_week": tw.get("quit_week"),
         "children": "children at home" in prof, "wfh_pref_z": float(tr.get("wfh_pref_z") or 0.0), "profile": prof,
         "quit_risk_pct": (lambda m: int(m.group(1)) if m else None)(__import__("re").search(r"quit-risk percentile (\d+)", prof))}
    f["sat_delta"] = round(f["sat_end"] - f["sat_base"], 2); f["wlb_delta"] = round(f["wlb_end"] - f["wlb_base"], 2)
    workload = tw.get("workload") or {}
    f["ai_assisted"] = bool(tw.get("ai_assisted"))
    f["hours_released"] = workload.get("unassisted_hours", 0) - workload.get("human_hours", 0)
    return f


def _wf_topics(f: dict[str, Any]) -> list[str]:
    t = []
    if f["commute_2way_h"] >= 2.0: t.append("long_commute")
    if f["offered"] and f["take_up"] is not None and f["take_up"] >= 0.5: t += ["wfh_days_used", "commute_saved"]
    if f["offered"] and f["take_up"] is not None and f["take_up"] < 0.25: t.append("option_unused")
    if not f["offered"] and f["relative_deprivation"] > 0.05: t.append("not_offered_teammates_were")
    if f["sat_delta"] >= 0.3: t.append("satisfaction_up")
    elif f["sat_delta"] <= -0.3: t.append("satisfaction_down")
    else: t.append("satisfaction_stable")
    if f["wlb_delta"] >= 0.3: t.append("work_life_balance_up")
    if f["children"]: t.append("family")
    if f["attachment"] >= 0.7: t.append("attachment_strong")
    elif f["attachment"] <= 0.4: t.append("attachment_weak")
    if f["quit_week"]: t.append("resigned")
    if f["manager"]: t.append("manager_role")
    if f["offered"] and f["wfh_pref_z"] > 1.0: t.append("wants_more_days")
    t.append("performance_unchanged")
    return t


def _sentiment(score: float, lo: float = 6.0, hi: float = 7.5) -> str:
    return "negative" if score <= lo else "positive" if score >= hi else "neutral"


def _wf_template(f: dict[str, Any], metric: str) -> str:
    if metric == "performance" and f.get("ai_assisted"):
        hours = f["hours_released"]
        effort = f"{hours:.1f} hours available for other work" if hours >= 0 else f"{-hours:.1f} additional hours of work"
        return f"With the assumed AI assistance, review and correction included, my modeled tasks leave {effort} over the period. That is a workload estimate; the model does not assume a change in my performance rating or likelihood of leaving."
    c, days = f["company"], f["wfh_days"]
    commute = f"{f['commute_2way_h']:.1f} hours a day" if f["commute_2way_h"] >= 1.0 else f"about {int(round(f['commute_2way_h'] * 60))} minutes a day"
    if metric == "attrition":
        if f["quit_week"]:
            why = []
            if f["commute_2way_h"] >= 2.0: why.append(f"the commute, {commute} door to door")
            if not f["offered"] and f["relative_deprivation"] > 0.05: why.append("watching half my team work from home on Wednesdays and Fridays while I came in")
            if f["sat_delta"] <= -0.3: why.append("my satisfaction had been slipping for weeks")
            if f["attachment"] <= 0.4: why.append("I never felt very attached here")
            if not why:
                why.append(f"nothing about the arrangement; I was already among the more likely to move on (quit-risk percentile {f['quit_risk_pct']})" if f.get("quit_risk_pct") is not None else "nothing about the arrangement; the week-to-week odds just went against me")
            return f"Yes, and I left in week {f['quit_week']}. What weighed most was {', and '.join(why)}."
        hold = []
        if f["attachment"] >= 0.7: hold.append("I am attached to this place")
        if f["offered"] and days >= 10: hold.append(f"the {days} home days this autumn made the week workable")
        if f["sat_end"] >= 7.5: hold.append("I like the job")
        if not hold:
            hold.append("the thought came and went" if f["sat_end"] > 6.0 else "I keep an eye on openings")
        tail = f" The commute is {commute}, which is the part I would change." if f["commute_2way_h"] >= 2.0 else ""
        return f"Not seriously: {', and '.join(hold)}.{tail}"
    if metric == "satisfaction":
        d = f["sat_delta"]
        if d >= 0.3: return f"It went up, from about {f['sat_base']:.1f} to {f['sat_end']:.1f} out of ten. " + ("The home days took the edge off the week." if f["offered"] else "The team has been steady and the work is going well.")
        if d <= -0.3:
            reason = "being the one in the office while teammates were at home wore on me" if (not f["offered"] and f["relative_deprivation"] > 0.05) else "the weeks just got heavier"
            return f"It slipped, from about {f['sat_base']:.1f} to {f['sat_end']:.1f}; {reason}."
        return f"About the same, around {f['sat_end']:.1f} out of ten. Nothing in the policy changed what my job is."
    if metric == "work_life_balance":
        if f["offered"]:
            if f["take_up"] is not None and f["take_up"] >= 0.5:
                fam = " With the children at home that is the difference between seeing them at dinner and not." if f["children"] else ""
                return f"I used {days} of my {f['eligible_days']} eligible days. On those days I got {commute} back and my work-life balance moved from {f['wlb_base']:.1f} to {f['wlb_end']:.1f}.{fam}"
            if f["take_up"] is not None and f["take_up"] < 0.25:
                return f"I only took {days} of {f['eligible_days']} days; I work better in the office and my commute is {commute}, so the option mattered more than the days. Knowing I could stay home when needed was enough."
            return f"I took it some weeks ({days} of {f['eligible_days']} days). It helped on the days I used it; balance went from {f['wlb_base']:.1f} to {f['wlb_end']:.1f}."
        if f["relative_deprivation"] > 0.05:
            return f"I was not offered it, so every Wednesday and Friday I was in the office while part of my team was at home. It did not change my hours, but it changed how fair the week felt."
        return "I was not offered it, so my week did not change: five days in, " + f"{commute} on the road."
    if metric == "performance":
        if f["manager"]: return "Coordination took a little more planning on home days, but the team's output did not move; my grade reflects that."
        return "No. The work is the same from home or from the office; my review grade did not move, which is what I expected."
    return ""


def _wf_group(f: dict[str, Any]) -> str:
    return "offered" if f["offered"] else "not offered"


def interview_workforce(ctx: InstanceContext, scenario_id: str, run_id: str, n: int, voice, company: str) -> dict[str, Any]:
    reader = RunReader(ctx.id, scenario_id, run_id)
    tw_path = reader.dir / "twins.json"
    if not tw_path.exists():
        raise FileNotFoundError(f"{tw_path} (run has no twins.json)")
    twins = json.loads(tw_path.read_text()).get("twins") or []
    rng = _rng(7)
    quitters = [t for t in twins if t.get("quit_week")]
    stayers = [t for t in twins if not t.get("quit_week")]
    n_q = min(len(quitters), max(2, n // 3))
    picks = list(rng.choice(len(quitters), n_q, replace=False)) if n_q else []
    sample = [quitters[i] for i in picks]
    # stayers stratified by offered / not offered and manager / non-manager
    strata: dict[tuple[bool, bool], list[dict[str, Any]]] = defaultdict(list)
    for t in stayers:
        strata[(bool(t.get("offered")), t.get("role") == "manager")].append(t)
    per = max(1, (n - n_q) // max(1, len(strata)))
    for key in sorted(strata):
        pool = strata[key]
        k = min(len(pool), per)
        sample += [pool[i] for i in rng.choice(len(pool), k, replace=False)]
    interviews = []
    for tw in sample:
        f = _wf_facts(tw, company)
        topics = _wf_topics(f)
        qa = []
        for metric, q in WF_QUESTIONS:
            ans = voice(f, metric, q, _wf_template(f, metric))
            qa.append({"metric": metric, "question": q, "answer": ans, "topics": [t for t in topics if t in _wf_metric_topics(metric)], "sentiment": _sentiment(f["sat_end"])})
        interviews.append({"agent_id": tw.get("agent_id"), "role": tw.get("role"), "group": _wf_group(f), "outcome": f"resigned week {f['quit_week']}" if f["quit_week"] else "stayed",
                           "facts": {k: v for k, v in f.items() if k not in ("profile", "company")}, "profile": f["profile"], "topics": topics, "sentiment": _sentiment(f["sat_end"]), "qa": qa})
    return {"interviews": interviews, "group_label": "offer"}


def _wf_metric_topics(metric: str) -> set[str]:
    return {"attrition": {"long_commute", "not_offered_teammates_were", "satisfaction_down", "attachment_weak", "attachment_strong", "resigned", "wfh_days_used"},
            "satisfaction": {"satisfaction_up", "satisfaction_down", "satisfaction_stable", "not_offered_teammates_were"},
            "work_life_balance": {"commute_saved", "wfh_days_used", "option_unused", "family", "work_life_balance_up", "long_commute", "not_offered_teammates_were", "wants_more_days"},
            "performance": {"performance_unchanged", "manager_role"}}[metric]


# ----------------------------------------------------------------------------- process interviews

PR_QUESTIONS = [
    ("completion", "Why do purchase-order items take as long as they do to clear?"),
    ("backlog", "What is sitting in your queue right now, and why?"),
    ("exceptions", "Where does rework come from in your step?"),
    ("handoffs", "Whose work do you wait for, and who waits for you?"),
]
ROLE_LABELS = {"purchasing_clerk": "Purchasing clerk", "buyer": "Buyer / requisitioner", "goods_receipt": "Goods receipt clerk", "ap_invoice": "AP invoice clerk", "ap_payment": "AP payment specialist"}


def _pr_facts(role: str, head: dict[str, Any], alt_mult: float | None) -> dict[str, Any]:
    wf = (head.get("workforce") or {}).get(role) or {}
    util = float((head.get("utilization") or {}).get(role) or 0.0)
    return {"role": role, "label": ROLE_LABELS.get(role, role), "utilization": util, "active_headcount": wf.get("active_headcount"), "headcount_simulated": wf.get("headcount_simulated"),
            "actions_per_hour": wf.get("actions_per_active_hour"), "mean_wait_h": head.get("mean_wait_h"), "p90_wait_h": head.get("p90_wait_h"), "queued_actions_end": head.get("queued_actions_end"),
            "backlog_end": head.get("backlog_end"), "completion_rate_14d": head.get("completion_rate_14d"), "median_cycle_hours": head.get("median_cycle_hours_completed"),
            "exception_rate": head.get("exception_rate"), "handoffs_per_case": head.get("handoffs_per_case"), "arrivals": head.get("arrivals"), "events": head.get("events"), "headcount_mult": alt_mult}


def _pr_topics(f: dict[str, Any]) -> list[str]:
    t = []
    r = f["role"]
    if r == "ap_payment": t += ["payment_run_cadence", "payment_blocks"]
    if r == "ap_invoice": t += ["waiting_for_goods_receipt", "payment_blocks", "vendor_timing"]
    if r == "goods_receipt": t += ["hand_off_dependency", "vendor_timing"]
    if r in ("purchasing_clerk", "buyer"): t += ["batch_automation", "rework_exceptions"]
    if f["utilization"] >= 0.6: t.append("capacity_strain")
    elif f["utilization"] <= 0.25: t.append("capacity_slack")
    if (f["exception_rate"] or 0) >= 4: t.append("rework_exceptions")
    t.append("hand_off_dependency")
    if f.get("headcount_mult") and f["headcount_mult"] > 1.05:
        t.append("more_people_same_queue" if (f["completion_rate_14d"] or 0) < 15 else "throughput_up")
    if f.get("headcount_mult") and f["headcount_mult"] < 0.95:
        t.append("fewer_people_same_queue" if f["utilization"] < 0.6 else "throughput_down")
    return list(dict.fromkeys(t))


def _pr_template(f: dict[str, Any], metric: str) -> str:
    util = f"{f['utilization'] * 100:.0f}%"
    hc = f"{f['headcount_simulated']:.0f}" if f.get("headcount_simulated") else "our"
    more = f" There are {hc} of us now instead of {f['active_headcount']:.0f}," if f.get("headcount_mult") and abs(f["headcount_mult"] - 1) > 0.05 and f.get("active_headcount") else ""
    if metric == "completion":
        if f["role"] == "ap_payment":
            return f"Clearing only happens in the payment run, so an invoice that is ready on a Tuesday waits for the next run whatever we do. Of the items live at the cutoff, {f['completion_rate_14d']:.1f}% cleared within two weeks; the median completed item had been open {f['median_cycle_hours'] / 24:.0f} days.{more} but the calendar did not change."
        if f["role"] == "ap_invoice":
            return f"Most of the time is not in our hands: an invoice cannot be cleared until the goods receipt is posted and the amounts match, and many vendors invoice before the goods arrive. We are at {util} of capacity, so the queue is not the bottleneck; the match is."
        if f["role"] == "goods_receipt":
            return f"We post the receipt when the goods arrive; what comes before (the order) and after (the invoice match and the payment run) sets the cycle time. Our utilization is {util}."
        return f"The order side is quick; {f['completion_rate_14d']:.1f}% of live items completed within the two weeks, and almost all of the remaining time is the invoice side waiting for receipts and the payment run."
    if metric == "backlog":
        q = f["queued_actions_end"] or 0; b = f["backlog_end"] or 0
        if f["utilization"] >= 0.6:
            return f"We are at {util} of capacity; actions wait on average {f['mean_wait_h']:.1f} hours and the slowest tenth wait {f['p90_wait_h']:.0f} hours. About {q:,.0f} actions were queued at the end of the horizon across all roles.{more} so the queue is shorter than it was."
        return f"Not much that is ours: utilization is {util}. The {b:,.0f} open items are mostly waiting for a prerequisite step or for the next payment run, not for a free pair of hands.{more} which changes little when the wait is structural."
    if metric == "exceptions":
        er = f["exception_rate"] or 0
        if f["role"] in ("purchasing_clerk", "buyer"):
            return f"Price and quantity changes after the order is placed, and deleted lines. About {er:.1f}% of items hit an exception in the two weeks; each one sends the item back through a change step before the receipt or invoice can match."
        if f["role"] == "ap_invoice":
            return f"Cancelled invoice receipts and subsequent invoices: {er:.1f}% of items had an exception. Most come from the vendor invoicing before the goods receipt exists, so we record, block, and re-record."
        if f["role"] == "ap_payment":
            return f"Payment blocks. We set and remove them when the match fails; {er:.1f}% of items had at least one exception, and a block costs the item at least one payment-run cycle."
        return f"Cancelled receipts when the delivery does not match the order line; {er:.1f}% of items had an exception."
    if metric == "handoffs":
        h = f["handoffs_per_case"] or 0
        who = {"purchasing_clerk": "buyers release the requisition before I can create the line; goods receipt and accounts payable wait for me",
               "buyer": "the SRM batch transfer; purchasing clerks wait for my release",
               "goods_receipt": "the vendor's delivery; the invoice clerks wait for my receipt",
               "ap_invoice": "the goods receipt and the vendor's invoice; the payment specialists wait for my record",
               "ap_payment": "the invoice clerks' record and the removal of any block; the vendor waits for me"}[f["role"]]
        return f"I wait for {who}. An active item changes hands about {h:.1f} times in two weeks, and the batch jobs do the routine transfers in between."
    return ""


def interview_process(ctx: InstanceContext, scenario_id: str, run_id: str, n: int, voice, company: str, alt_mult: float | None) -> dict[str, Any]:
    reader = RunReader(ctx.id, scenario_id, run_id)
    summ = json.loads((reader.dir / "summary.json").read_text())
    head = summ.get("headline") or {}
    interviews = []
    for role in ROLE_LABELS:
        if role not in (head.get("utilization") or {}):
            continue
        f = _pr_facts(role, head, alt_mult)
        topics = _pr_topics(f)
        strain = "negative" if f["utilization"] >= 0.6 else "positive" if f["utilization"] <= 0.25 else "neutral"
        qa = []
        for metric, q in PR_QUESTIONS:
            ans = voice(f, metric, q, _pr_template(f, metric))
            qa.append({"metric": metric, "question": q, "answer": ans, "topics": [t for t in topics if t in _pr_metric_topics(metric)], "sentiment": strain})
        interviews.append({"agent_id": role, "role": role, "group": ROLE_LABELS.get(role, role), "outcome": f"utilization {f['utilization'] * 100:.0f}%", "facts": f,
                           "profile": f"{ROLE_LABELS.get(role, role)}: {f['headcount_simulated']:.0f} people simulated ({f['active_headcount']:.0f} active before the cutoff), {f['actions_per_hour']:.1f} actions per active hour." if f.get("headcount_simulated") else ROLE_LABELS.get(role, role),
                           "topics": topics, "sentiment": strain, "qa": qa})
    return {"interviews": interviews, "group_label": "role"}


def _pr_metric_topics(metric: str) -> set[str]:
    return {"completion": {"payment_run_cadence", "waiting_for_goods_receipt", "vendor_timing", "more_people_same_queue", "throughput_up", "fewer_people_same_queue", "throughput_down"},
            "backlog": {"capacity_slack", "capacity_strain", "payment_run_cadence", "more_people_same_queue", "fewer_people_same_queue"},
            "exceptions": {"rework_exceptions", "payment_blocks"},
            "handoffs": {"hand_off_dependency", "batch_automation"}}[metric]


# ----------------------------------------------------------------------------- market interviews (companies)

MK_QUESTIONS = [
    ("tokens", "How will your token use change over the next eight weeks?"),
    ("models", "Which models will your workloads run on, and why?"),
    ("spend", "What will you spend, and what drives it?"),
]
SEGMENT_LABELS = {"programming": "coding", "roleplay": "roleplay and creative", "market": "general"}


def _mk_facts(a: dict[str, Any], head: dict[str, Any]) -> dict[str, Any]:
    seg = a["segment"]
    tok8 = float(sum(a["tokens"])); start = float(a.get("start_tokens_week") or a["tokens"][0])
    growth = (a["tokens"][-1] / start - 1) * 100 if start > 0 else 0.0
    price = head.get("segment_price", {}).get(seg, [])
    mix = head.get("segment_mix_end", {}).get(seg, {})
    top = sorted(mix.items(), key=lambda kv: -kv[1])[:3]
    newm = [m for m in head.get("new_models_listed", []) if mix.get(m, 0) >= 0.01]
    return {"name": a["name"], "segment": seg, "segment_label": SEGMENT_LABELS.get(seg, seg), "category": a.get("category"), "subcategory": a.get("subcategory"),
            "persistence": a.get("persistence"), "start_tokens_week": start, "tokens_8w": tok8, "growth_pct": growth, "spend_8w": float(sum(a["spend_usd"])),
            "price_start": price[0] if price else None, "price_end": price[-1] if price else None, "top_models": top, "new_models": newm,
            "repriced": list((head.get("price_multipliers") or {}).keys()), "t0": head.get("t0")}


def _mk_topics(f: dict[str, Any]) -> list[str]:
    t = ["coding_workload"] if f["segment"] == "programming" else ["roleplay_workload"] if f["segment"] == "roleplay" else []
    t.append("one_off_job" if f["persistence"] == "burst" else "steady_product" if f["persistence"] == "steady" else "growing" if f["growth_pct"] > 0 else "fading")
    if f["growth_pct"] >= 10: t.append("growing")
    elif f["growth_pct"] <= -10: t.append("fading")
    if f["price_start"] and f["price_end"]:
        if f["price_end"] > f["price_start"] * 1.03: t.append("price_up")
        elif f["price_end"] < f["price_start"] * 0.97: t.append("price_down")
    if f["repriced"] and f["segment"] == "programming": t.append("switched_models")
    if f["new_models"]: t.append("new_models")
    return list(dict.fromkeys(t))


def _mk_template(f: dict[str, Any], metric: str) -> str:
    wk = f["start_tokens_week"] / 1e9; tot = f["tokens_8w"] / 1e9
    if metric == "tokens":
        kind = {"burst": "We ran as a one-off job: a week or two of heavy traffic, then little.", "recurring": "Our traffic comes and goes from week to week.",
                "steady": "We are a steady product with traffic every week."}.get(f["persistence"], "")
        return f"{kind} We were using about {wk:,.1f} billion tokens a week before {f['t0']}; over the next eight weeks the simulation has us at {tot:,.1f} billion in total, ending {f['growth_pct']:+.0f}% against where we started."
    if metric == "models":
        mods = ", ".join(f"{m.split('/')[-1]} ({v * 100:.0f}%)" for m, v in f["top_models"]) or "the models in our segment"
        extra = f" Newly listed models that picked up work: {', '.join(m.split('/')[-1] for m in f['new_models'][:3])}." if f["new_models"] else ""
        rp = f" The repriced model ({', '.join(m.split('/')[-1] for m in f['repriced'])}) costs twice as much, so some of our {f['segment_label']} workloads moved off it." if f["repriced"] and f["segment"] == "programming" else ""
        return f"Our {f['segment_label']} workloads end the period mostly on {mods}.{extra}{rp}"
    if metric == "spend":
        pr = f" The blended list price of our workloads moved from ${f['price_start']:.2f} to ${f['price_end']:.2f} per million tokens." if f["price_start"] and f["price_end"] else ""
        return f"About ${f['spend_8w']:,.0f} over eight weeks at list prices; caching and discounts would bring the bill down.{pr} Volume, not price, drives most of the change."
    return ""


def interview_market(ctx: InstanceContext, scenario_id: str, run_id: str, n: int, voice, company: str) -> dict[str, Any]:
    reader = RunReader(ctx.id, scenario_id, run_id)
    head = json.loads((reader.dir / "summary.json").read_text()).get("headline") or {}
    apps = head.get("apps", [])
    # the largest companies first, then a spread across segments
    order = sorted(range(len(apps)), key=lambda i: -sum(apps[i]["tokens"]))
    pick = order[: max(1, n // 2)] + [i for i in order[n // 2:] if apps[i]["segment"] != "market"][: n - n // 2]
    interviews = []
    for i in pick[:n]:
        f = _mk_facts(apps[i], head)
        topics = _mk_topics(f)
        sent = "positive" if f["growth_pct"] >= 10 else "negative" if f["growth_pct"] <= -10 else "neutral"
        qa = [{"metric": m, "question": q, "answer": voice(f, m, q, _mk_template(f, m)), "topics": topics, "sentiment": sent} for m, q in MK_QUESTIONS]
        interviews.append({"agent_id": f"app:{apps[i]['app_id']}", "role": f["segment"], "group": f["segment_label"], "outcome": f"{f['growth_pct']:+.0f}% over eight weeks",
                           "facts": f, "profile": f"{f['name']}: {f['subcategory'] or f['category'] or 'unclassified'} app, {f['persistence']} traffic, {f['start_tokens_week'] / 1e9:,.1f} billion tokens a week at the cutoff.",
                           "topics": topics, "sentiment": sent, "qa": qa})
    return {"interviews": interviews, "group_label": "segment"}


def _mk_insights(block: dict[str, Any], title: str) -> list[str]:
    iv = block["interviews"]; n = len(iv)
    out = []
    oneoff = sum(1 for i in iv if "one_off_job" in i["topics"]); fading = sum(1 for i in iv if "fading" in i["topics"]); growing = sum(1 for i in iv if "growing" in i["topics"])
    out.append(f"{title}: {growing} of {n} interviewed companies expect to grow by 10% or more over eight weeks and {fading} expect to fall by 10% or more; {oneoff} describe themselves as one-off jobs.")
    sw = sum(1 for i in iv if "switched_models" in i["topics"])
    if sw:
        out.append(f"{title}: {sw} coding companies moved some work off the repriced model.")
    nm = sum(1 for i in iv if "new_models" in i["topics"])
    if nm:
        out.append(f"{title}: {nm} of {n} companies' segments put work on models listed after the cutoff.")
    spend = sum(i["facts"]["spend_8w"] for i in iv)
    out.append(f"{title}: the interviewed companies spend ${spend:,.0f} at list prices over the eight weeks in this run.")
    return out


# ----------------------------------------------------------------------------- adoption interviews (groups of adopters)

AD_QUESTIONS = [
    ("adoption", "How many of your group will be using the technology by the end of the horizon?"),
    ("drivers", "What drives the change?"),
]


def _ad_facts(g: dict[str, Any], head: dict[str, Any]) -> dict[str, Any]:
    cs = g.get("central_share") or []
    start = float(g.get("start_share") or 0.0)
    end = float(cs[-1]) if cs else start
    mult = head.get("hazard_multipliers") or {}
    return {"name": g["label"], "group": g["group"], "start_share": start, "end_share": end, "change_pts": (end - start) * 100, "periods": head.get("horizon_periods"),
            "cutoff_date": head.get("cutoff_date"), "outcome": head.get("outcome"), "spec": (head.get("calibration") or {}).get("spec") or {},
            "boosted": g["group"] in mult, "multiplier": mult.get(g["group"])}


def _ad_topics(f: dict[str, Any]) -> list[str]:
    t = ["adoption_up" if f["change_pts"] >= 0.5 else "adoption_down" if f["change_pts"] <= -0.5 else "adoption_flat"]
    t.append("imitation" if f["spec"].get("form") == "imitation" else "external_influence")
    if f["boosted"]:
        t.append("programme")
    return t


def _ad_template(f: dict[str, Any], metric: str) -> str:
    if metric == "adoption":
        return (f"At {f['cutoff_date']} about {f['start_share'] * 100:.1f}% of us use it; in the simulation that is {f['end_share'] * 100:.1f}% after "
                f"{f['periods']} periods ({f['change_pts']:+.1f} points).")
    form = ("we follow the others who already use it, in our own group and in the whole population" if f["spec"].get("form") == "imitation"
            else "outside pressure moves a steady fraction of the remaining non-users each period")
    extra = f" A programme multiplies our non-users' chance of starting by {f['multiplier']:.1f}." if f["boosted"] else ""
    return f"In the simulation, {form}.{extra}"


def interview_adoption(ctx: InstanceContext, scenario_id: str, run_id: str, n: int, voice, company: str) -> dict[str, Any]:
    reader = RunReader(ctx.id, scenario_id, run_id)
    head = json.loads((reader.dir / "summary.json").read_text()).get("headline") or {}
    interviews = []
    for g in (head.get("groups") or [])[:n]:
        f = _ad_facts(g, head)
        topics = _ad_topics(f)
        sent = "positive" if f["change_pts"] >= 0.5 else "negative" if f["change_pts"] <= -0.5 else "neutral"
        qa = [{"metric": m, "question": q, "answer": voice(f, m, q, _ad_template(f, m)), "topics": topics, "sentiment": sent} for m, q in AD_QUESTIONS]
        interviews.append({"agent_id": f"group:{g['group']}", "role": "group", "group": g["label"], "outcome": f"{f['change_pts']:+.1f} points",
                           "facts": f, "profile": f"{g['label']}: a simulated population of adopters, {f['start_share'] * 100:.1f}% using at the cutoff.",
                           "topics": topics, "sentiment": sent, "qa": qa})
    return {"interviews": interviews, "group_label": "group"}


def _ad_insights(block: dict[str, Any], title: str) -> list[str]:
    iv = block["interviews"]; n = len(iv)
    up = sum(1 for i in iv if "adoption_up" in i["topics"])
    out = [f"{title}: {up} of {n} simulated groups gain half a point of adoption or more over the horizon."]
    if iv:
        top = max(iv, key=lambda i: i["facts"]["end_share"])
        out.append(f"{title}: the highest simulated adoption at the end of the horizon is {top['group']} at {top['facts']['end_share'] * 100:.1f}%.")
    return out


# ----------------------------------------------------------------------------- voices

def template_voice(facts: dict[str, Any], metric: str, question: str, rendered: str) -> str:
    return rendered


def llm_voice(model: str):
    import httpx
    key = os.environ.get("ANTHROPIC_API_KEY", "")

    def voice(facts: dict[str, Any], metric: str, question: str, rendered: str) -> str:
        if not key:
            return rendered
        prompt = (f"You are the simulated employee described below, answering an interview question in two or three sentences, first person, concrete, no marketing tone. "
                  f"Stay strictly consistent with the facts; do not invent numbers.\nFacts: {json.dumps({k: v for k, v in facts.items() if k != 'profile'}, default=str)}\n"
                  f"Profile: {facts.get('profile', '')}\nQuestion: {question}\nA faithful plain rendering of the facts, for reference: {rendered}")
        try:
            r = httpx.post("https://api.anthropic.com/v1/messages", json={"model": model, "max_tokens": 220, "messages": [{"role": "user", "content": prompt}]}, timeout=30,
                           headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
            r.raise_for_status()
            text = "".join(c.get("text", "") for c in r.json().get("content", [])).strip()
            return text or rendered
        except Exception:  # noqa: BLE001
            return rendered
    return voice


# ----------------------------------------------------------------------------- aggregation

def _aggregate(block: dict[str, Any]) -> None:
    iv = block["interviews"]
    n = len(iv)
    counts: Counter[str] = Counter()
    by_group: dict[str, Counter[str]] = defaultdict(Counter)
    group_n: Counter[str] = Counter()
    for i in iv:
        group_n[i["group"]] += 1
        for t in set(i["topics"]):
            counts[t] += 1; by_group[i["group"]][t] += 1
    block["topics"] = [{"id": t, "label": TOPIC_LABELS.get(t, t), "count": c, "share": round(c / n, 3) if n else 0,
                        "by_group": {g: round(by_group[g][t] / group_n[g], 3) for g in group_n}} for t, c in counts.most_common()]
    sent = Counter(i["sentiment"] for i in iv)
    block["sentiment"] = {"distribution": {k: sent.get(k, 0) for k in ("negative", "neutral", "positive")}, "n": n,
                          "by_group": {g: {k: sum(1 for i in iv if i["group"] == g and i["sentiment"] == k) for k in ("negative", "neutral", "positive")} for g in group_n}}
    block["groups"] = dict(group_n)
    block["n_interviews"] = n


def _wf_insights(block: dict[str, Any], title: str) -> list[str]:
    iv = block["interviews"]; n = len(iv)
    out = []
    quitters = [i for i in iv if "resigned" in i["topics"]]
    if quitters:
        lc = sum(1 for i in quitters if "long_commute" in i["topics"]); rd = sum(1 for i in quitters if "not_offered_teammates_were" in i["topics"])
        out.append(f"{title}: of the {len(quitters)} interviewed employees who resigned, {lc} name a commute of two hours a day or more and {rd} name being left in the office while teammates worked from home.")
    offered = [i for i in iv if i["group"] == "offered"]; not_off = [i for i in iv if i["group"] == "not offered"]
    if offered:
        used = sum(1 for i in offered if "wfh_days_used" in i["topics"]); up = sum(1 for i in offered if "satisfaction_up" in i["topics"])
        out.append(f"{title}: {used} of {len(offered)} offered employees use the home days most weeks; {up} of {len(offered)} report higher job satisfaction than in August.")
    if not_off:
        rd = sum(1 for i in not_off if "not_offered_teammates_were" in i["topics"]); down = sum(1 for i in not_off if "satisfaction_down" in i["topics"])
        out.append(f"{title}: {rd} of {len(not_off)} employees not offered the policy bring up the comparison with teammates who were; {down} report lower satisfaction.")
    s = block["sentiment"]["distribution"]
    out.append(f"{title}: sentiment across {n} interviews is {s['positive']} positive, {s['neutral']} neutral, {s['negative']} negative (from each twin's end-of-period job satisfaction).")
    perf = sum(1 for i in iv if "performance_unchanged" in i["topics"])
    out.append(f"{title}: {perf} of {n} say the arrangement did not change their output, matching the null performance effect in the experiment.")
    return out


def _pr_insights(block: dict[str, Any], title: str) -> list[str]:
    iv = block["interviews"]
    out = []
    strain = [i["group"] for i in iv if "capacity_strain" in i["topics"]]; slack = [i["group"] for i in iv if "capacity_slack" in i["topics"]]
    if slack:
        out.append(f"{title}: {', '.join(slack)} report spare capacity (utilization at or below 25%); the waiting is structural, not a staffing shortage.")
    if strain:
        out.append(f"{title}: {', '.join(strain)} report strain (utilization 60% or more).")
    if any("payment_run_cadence" in i["topics"] for i in iv):
        f = next(i["facts"] for i in iv if i["role"] == "ap_payment")
        out.append(f"{title}: the payment specialists point at the payment-run calendar as the clock behind clearing: {f['completion_rate_14d']:.1f}% of live items cleared within 14 days, median completed cycle {f['median_cycle_hours'] / 24:.0f} days.")
    if any("more_people_same_queue" in i["topics"] for i in iv):
        out.append(f"{title}: with the larger workforce the roles report shorter personal queues but the same completion rate, because the match and the payment run, not hands, set the pace.")
    if any("fewer_people_same_queue" in i["topics"] for i in iv):
        out.append(f"{title}: with the pre-expansion staffing the roles report fuller days but the same completion rate, because the match and the payment run, not hands, set the pace.")
    if any("throughput_down" in i["topics"] for i in iv):
        out.append(f"{title}: with the pre-expansion staffing at least one role is strained (utilization 60% or more) and throughput falls.")
    if any("throughput_up" in i["topics"] for i in iv):
        out.append(f"{title}: with the larger workforce the roles report higher throughput.")
    ex = [i for i in iv if "rework_exceptions" in i["topics"]]
    if ex:
        out.append(f"{title}: {len(ex)} of {len(iv)} roles describe rework (price and quantity changes, cancelled receipts, payment blocks) as the source of repeated steps.")
    return out


# ----------------------------------------------------------------------------- entry point

def build_insights(ctx: InstanceContext, n_per_scenario: int = 24, model: str | None = None) -> dict[str, Any]:
    roles = scenario_roles(ctx)
    titles = {s["id"]: s["title"] for s in list_scenarios(ctx)}
    company = str(ctx.meta.get("company", ctx.meta.get("title", ctx.id)))
    voice = llm_voice(model) if model else template_voice
    method = f"llm:{model}" if model and os.environ.get("ANTHROPIC_API_KEY") else "template"
    out: dict[str, Any] = {"instance": ctx.id, "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "method": method,
                           "note": "Simulated interviews: every answer is rendered from the agent's own simulated record (profile, traits, states, decisions or queue statistics). Nothing here was said by a real person.",
                           "scenarios": {}}
    need = "twins.json" if ctx.world_type == "workforce" else "summary.json"
    for sid, role in roles.items():
        rid = next((r["run_id"] for r in list_runs(ctx.id) if r["scenario"] == sid and r["complete"] and (ctx.runs_dir / sid / r["run_id"] / need).exists()), None)
        if not rid:
            out["scenarios"][role] = {"scenario": sid, "title": titles.get(sid, sid), "run_id": None, "error": "no completed run"}
            continue
        alt_mult = None
        if role.startswith("alternative") and ctx.world_type == "process":
            from ..scenarios import load_scenario
            for iv in load_scenario(ctx, sid).get("interventions") or []:
                if iv.get("type") in ("headcount_shift", "capacity") and iv.get("role", "all") == "all":
                    alt_mult = float(iv.get("multiplier", 1.0))
        try:
            if ctx.world_type == "workforce":
                block = interview_workforce(ctx, sid, rid, n_per_scenario, voice, company)
            elif ctx.world_type == "market":
                block = interview_market(ctx, sid, rid, n_per_scenario, voice, company)
            elif ctx.world_type == "adoption":
                block = interview_adoption(ctx, sid, rid, n_per_scenario, voice, company)
            else:
                block = interview_process(ctx, sid, rid, n_per_scenario, voice, company, alt_mult)
        except FileNotFoundError as e:
            out["scenarios"][role] = {"scenario": sid, "title": titles.get(sid, sid), "run_id": rid, "error": str(e)}
            continue
        questions = {"workforce": WF_QUESTIONS, "market": MK_QUESTIONS, "adoption": AD_QUESTIONS}.get(ctx.world_type, PR_QUESTIONS)
        basis = {"workforce": "each twin's end-of-period job satisfaction: 6 or below negative, 7.5 or above positive",
                 "market": "the company's simulated weekly tokens at the end of the eight weeks against the start: up 10% or more positive, down 10% or more negative",
                 "adoption": "the group's simulated adoption at the end of the horizon against the cutoff: up half a point or more positive, down half a point or more negative"}.get(
                     ctx.world_type, "role utilization in the run: 60% or more negative (strained), 25% or less positive (spare capacity)")
        block.update({"scenario": sid, "title": titles.get(sid, sid), "run_id": rid, "questions": questions, "sentiment_basis": basis})
        _aggregate(block)
        block["key_insights"] = {"workforce": _wf_insights, "market": _mk_insights, "adoption": _ad_insights}.get(ctx.world_type, _pr_insights)(block, role.capitalize())
        out["scenarios"][role] = block
    # cross-scenario comparison on sentiment and the most frequent topics
    b, a = out["scenarios"].get("baseline"), out["scenarios"].get("alternative")
    if b and a and "sentiment" in b and "sentiment" in a:
        sb, sa = b["sentiment"]["distribution"], a["sentiment"]["distribution"]
        out["comparison"] = {"sentiment": {"baseline": sb, "alternative": sa},
                             "topics": [{"id": t["id"], "label": t["label"], "baseline": t["share"], "alternative": next((x["share"] for x in a["topics"] if x["id"] == t["id"]), 0.0)} for t in b["topics"][:12]]}
        out["comparison"]["key_insights"] = [f"Negative sentiment: {sb['negative']} of {b['n_interviews']} interviews under the baseline versus {sa['negative']} of {a['n_interviews']} under the alternative."]
    ctx.runs_dir.mkdir(parents=True, exist_ok=True)
    (ctx.runs_dir / "insights.json").write_text(json.dumps(out, indent=1, default=str))
    return out
