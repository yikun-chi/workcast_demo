"""Build the public forecast board (one static page) from the records, their timestamp proofs, the scoreboard and the
frozen retrospective results.

Every number on the page is read from a record, scoreboard.json, the frozen charts_retro.json or the market series; none
is typed in. Styles and charts live in board/page/ and are inlined. Records and proofs are copied next to the page so
anyone can re-hash a forecast and verify the timestamp with `ots verify`.

    .venv/bin/python board/build_site.py --records /Volumes/PsychDynamicsData/workcast_board/records --out /Volumes/PsychDynamicsData/workcast_board/site \
      --retro board/results/charts_retro.json --market /Volumes/PsychDynamicsData/workcast_board/market.json
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
from datetime import date, timedelta
from pathlib import Path

PAGE = Path(__file__).resolve().parent / "page"
UNNAMED = re.compile(r"astra", re.I)                                   # the blend's language model stays unnamed on the public site (other GPT-6 models are data)


def fmt_tokens(x: float) -> str:
    if abs(x) >= 1e15:
        return f"{x / 1e12:,.0f}T"
    for unit, div in (("T", 1e12), ("B", 1e9), ("M", 1e6)):
        if abs(x) >= div:
            return f"{x / div:.1f}{unit}"
    return f"{x:,.0f}"


def pct(x: float | None, d: int = 1) -> str:
    return "–" if x is None else f"{x:.{d}f}%"


def public(x):
    """The frozen result files key this method by its internal name; the page and the records use a generic one."""
    if isinstance(x, dict):
        return {("llm" if k == "astra" else k): public(v) for k, v in x.items()}
    return [public(v) for v in x] if isinstance(x, list) else x


def accuracy(retro: dict) -> dict:
    """Everything on the page is accuracy: 100% minus token-weighted error, so higher is better."""
    flip = lambda v: None if v is None else 100 - v
    for st in retro["sets"].values():
        st["mean"] = {k: {h: flip(x) for h, x in m.items()} for k, m in st["mean"].items()}
    retro["weekly"]["series"] = {k: {h: [flip(x) for x in v] for h, v in s_.items()} for k, s_ in retro["weekly"]["series"].items()}
    for e in retro["scatter"]:
        e["error"] = {k: {h: flip(x) for h, x in m.items()} for k, m in e["error"].items()}
    return retro


def long_date(s: str) -> str:
    return f"{date.fromisoformat(s):%-d %b %Y}"


LABELS = {"combined": "WORKCAST combined (our forecast)", "T3": "Timestral, adjusted by a language model", "damped_trend": "Damped trend",
          "llm": "Large language model alone", "workcast": "WORKCAST simulation alone", "T1": "Timestral alone", "recent_trend": "Recent trend",
          "carry_forward": "No change", "market_growth": "Market growth", "damped_12w": "Damped trend, last 12 weeks", "damped_full": "Damped trend, full history"}
# what each method is given at a cutoff; all published before the cutoff (window lengths as in board/combo_study.py and orgsim/worlds/market.py)
INPUTS = {"combined": "The simulation, a large language model and the damped trend, blended with weights fixed on earlier weeks",
          "T3": "Timestral's and the simulation's forecasts, adjusted by a large language model",
          "damped_trend": "Each app's last 12 weeks",
          "llm": "Each app's last 12 weeks, market totals, app names and categories, plus what the model learned in training",
          "workcast": "All data since Jan 2025: apps, models, prices, launches",
          "T1": "Each app's weeks since Jan 2025 (Mistral's time-series foundation model)",
          "recent_trend": "Each app's last 8 weeks", "carry_forward": "Each app's last 4 weeks", "market_growth": "Each app's last 4 weeks and the market's last 9",
          "damped_12w": "Each app's last 12 weeks", "damped_full": "Each app's weeks since Jan 2025"}
SET_LABELS = [("heldout", "Held-out weeks"), ("earlier", "Earlier weeks"), ("backtest", "Backtest")]

NAV = ('<header class="nav"><div class="wrap"><a class="brand" href="/">Sumer S. Vaid</a><nav>'
       + "".join(f'<a href="/#{i}">{t}</a>' for i, t in (("about", "About"), ("building", "Open-Source Projects"), ("research", "Research"), ("publications", "Publications"), ("talks", "Talks"), ("contact", "Contact")))
       + '</nav><div class="act"><button class="icon" id="theme" type="button" aria-label="Toggle theme">'
         '<svg class="sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/></svg>'
         '<svg class="moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/></svg>'
         '</button><a class="btn" href="mailto:svaid@hbs.edu">Contact</a></div></div></header>')
HERO = ('<span class="badge">WORKCAST forecast board</span><h1>AI demand, forecast in advance<br>and scored in public.</h1>'
        '<p class="lede">Every week we publish a dated, tamper-evident forecast of how much AI the leading apps will use over the next eight weeks, then score the forecast in public against the standard methods and against a large language model alone. '
        'Our forecast blends the WORKCAST simulation, a large language model and a statistical trend model. Misses stay up.</p>')


def page(inner: str, data: dict) -> str:
    blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    return ('<!doctype html><html lang="en" class="dark"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#0a0a0a">'
            '<title>Forecast Board · WORKCAST</title><meta name="description" content="Dated, timestamped forecasts of AI demand, scored in public.">'
            "<script>try{var t=new URLSearchParams(location.search).get('theme')||localStorage.getItem('board-theme');if(t==='light')document.documentElement.classList.remove('dark')}catch(e){}</script>"
            f'<style>{(PAGE / "page.css").read_text()}</style></head><body>{NAV}<main class="wrap">{inner}</main>'
            '<footer class="foot"><div class="wrap"><div>© Sumer S. Vaid</div><div>WORKCAST · Data: OpenRouter Datasets API (CC BY 4.0)</div></div></footer>'
            f'<script type="application/json" id="board-data">{blob}</script><script>{(PAGE / "page.js").read_text()}</script></body></html>')


def strip(stats: list[tuple[str, str]]) -> str:
    return '<div class="strip">' + "".join(f'<div class="tile"><div class="big">{v}</div><div class="cap">{c}</div></div>' for v, c in stats) + "</div>"


def table(mean: dict, order: list[str], hz: tuple[str, ...], ours: str | None, note: dict[str, str] | None = None) -> str:
    head = "".join(f"<th>{h} wk</th>" for h in hz)
    rows = []
    for k in order:
        cells = "".join(f"<td>{pct(mean[k].get(h))}</td>" for h in hz)
        rows.append(f'<tr{" class=us" if k == ours else ""}><td>{LABELS.get(k, k)}{(note or {}).get(k, "")}<div class="meta">{INPUTS.get(k, "")}</div></td>{cells}<td>{pct(mean[k]["mean"])}</td></tr>')
    return f'<div class="tw"><table><tr><th>Method · what the method sees before each cutoff</th>{head}<th>Average</th></tr>{"".join(rows)}</table></div>'


def set_copy(sets: dict) -> dict[str, str]:
    """The sentence under the ranked chart for each set of weeks; every claim is tested against the numbers."""
    ho, ea, bt = sets["heldout"], sets["earlier"], sets["backtest"]
    hm, bm = ho["mean"], bt["mean"]
    order = sorted(hm, key=lambda k: -hm[k]["mean"])
    rank = f'Highest average accuracy of all {len(hm)} methods ({hm["combined"]["mean"]:.1f}%). ' if order[0] == "combined" else f'{LABELS[order[0]]} has the highest average accuracy. '
    behind = [h for h in ("1", "2", "4") if max(hm[k][h] for k in hm if k != "combined") > hm["combined"][h]]
    behind_txt = f'At {" and ".join(behind)} week{"s" if behind != ["1"] else ""} ahead another method was marginally ahead. ' if behind else "Best at every horizon. "
    held = (f'Weights fixed on earlier weeks, then scored once on {ho["n"]} new weekly cutoffs ({long_date(ho["first"])} to {long_date(ho["last"])}), all after the language model\'s training cutoff. '
            f'{rank}{behind_txt}The 1, 2 and 4 week columns cover {ho["n_by_horizon"]["1"]}, {ho["n_by_horizon"]["2"]} and {ho["n_by_horizon"]["4"]} cutoffs. '
            'The two Timestral rows were tested later on the same weeks. Eight-week results come from the live board.')
    earlier = (f'The {ea["n"]} weekly cutoffs ({long_date(ea["first"])} to {long_date(ea["last"])}) used to choose designs and fit the combined method\'s weights, so these scores flatter the combined method. '
               'Context only, not proof.')
    wins = [h for h in ("1", "2", "4", "8") if max(bm["damped_12w"][h], bm["damped_full"][h]) > bm["workcast"][h]]
    simple_lost = [h for h in ("1", "2", "4", "8") if max(bm[k][h] for k in ("carry_forward", "recent_trend", "market_growth")) >= bm["workcast"][h]]
    verdict = ("The simulation alone beats the three simple standards at every horizon" if not simple_lost else "The simulation alone is mixed against the three simple standards")
    verdict += (", but the damped trend beats the simulation at every horizon, with either history length." if len(wins) == 4 else
                f", and the damped trend beats the simulation at {', '.join(wins)} weeks." if wins else ", and the damped trend too.")
    back = (f'{bt["n"]} cutoffs four weeks apart, {long_date(bt["first"])} to {long_date(bt["last"])}, {bt["forecasts"]:,} forecasts. These weeks reach back before the language model\'s training cutoff, '
            f'so the language model and the combined method are not scored here. {verdict} That result is why the published forecast blends the simulation with the language model and the damped trend.')
    return {"heldout": held, "earlier": earlier, "backtest": back}


def spend_section(ev: dict) -> dict:
    """The backtest's forecasts of the leading apps' 8-week spend, window by window, against the standards."""
    ts = next(b for b in ev["business_validation"] if b["id"] == "top_spend")
    labels = ev["comparator_labels"]
    wins = [{"cutoff": w["cutoff"], "actual": w["actual"], "simulation": w["simulated"], **{k: w["baselines"][k] for k in labels}} for w in ts["windows"]]
    best = ts["best_baseline"]
    n, H = len(wins), int(ev["protocol"]["horizon_weeks"])
    mean_actual = sum(w["actual"] for w in wins) / n
    sim_pct, best_pct = 100 * ts["simulation_mae"] / mean_actual, 100 * ts["baseline_mae"][best] / mean_actual
    order = sorted(labels, key=lambda k: ts["baseline_mae"][k])
    rows = "".join(f'<tr{" class=us" if k == "simulation" else ""}><td>{"WORKCAST simulation alone" if k == "simulation" else LABELS[k]}<div class="meta">{INPUTS.get("workcast" if k == "simulation" else k, "")}</div></td>'
                   f'<td>${(ts["simulation_mae"] if k == "simulation" else ts["baseline_mae"][k]):.1f}M</td><td>{100 * (ts["simulation_mae"] if k == "simulation" else ts["baseline_mae"][k]) / mean_actual:.1f}%</td></tr>'
                   for k in sorted(["simulation", *labels], key=lambda k: ts["simulation_mae"] if k == "simulation" else ts["baseline_mae"][k]))
    verdict = (f'The simulation missed by ${ts["simulation_mae"]:.1f}M a window on average ({sim_pct:.0f}% of spend); the best standard forecast, {LABELS[best].lower()}, by ${ts["baseline_mae"][best]:.1f}M ({best_pct:.0f}%).'
               if ts["beats_best_baseline"] else
               f'The best standard forecast, {LABELS[best].lower()}, missed by ${ts["baseline_mae"][best]:.1f}M a window on average ({best_pct:.0f}% of spend); the simulation by ${ts["simulation_mae"]:.1f}M ({sim_pct:.0f}%).')
    html_ = (f'<section id="spend"><h2>AI spend, forecast against actual</h2><p class="sub">What the {ev["protocol"]["n_apps"]} leading apps spent at list prices over each {H}-week window, '
             f'{long_date(wins[0]["cutoff"])} to {long_date(wins[-1]["cutoff"])}, next to the forecast made at the start of the window from data before it. '
             f'Average window: ${mean_actual:.0f}M. {verdict} Simulation alone: these windows start before the language model\'s training data ends, so the blend is not scored here.</p>'
             f'<div class="legend" id="leg-spend"></div><div class="panel"><div id="c-spend"></div></div>'
             f'<details class="tv"><summary>Table view</summary><div class="tw"><table><tr><th>Method · what the method sees before each cutoff</th><th>Average miss</th><th>Share of spend</th></tr>{rows}</table>'
             f'<div class="tw" id="spend-table"></div></div></details></section>')
    return {"html": html_, "data": {"windows": wins, "best": best, "labels": {"simulation": "WORKCAST simulation alone", "actual": "Actual spend", **{k: LABELS[k] for k in labels}}, "H": H}}


def method_details(H: int) -> str:
    return (f'<details><summary>How the forecast works</summary><p>Our forecast blends three forecasts with weights fixed per horizon on earlier weeks: the WORKCAST simulation, '
            f'a large language model and the damped trend. At each Monday cutoff, WORKCAST carries every leading app forward {H} weeks from data before the cutoff: '
            'the app\'s growth path, whether the app stays among the leaders, and the models the app\'s workloads move to as new models launch and prices change. '
            'The simulation range is the 5th to 95th percentile of 20 runs. The language model reads each app\'s recent weeks and returns a forecast of the same quantities. '
            'The damped trend is the standard statistical forecast for series like these (Holt\'s method): the method projects each app\'s current level and growth, '
            'and lets the growth fade a little each week, capped at 15% a week. Accuracy is 100% minus the token-weighted error across the leading apps, so higher is better.</p></details>'
            '<details><summary>How to verify a forecast</summary><p>Each forecast is a read-only JSON record carrying the code version and a hash of every input table. '
            'The record\'s SHA-256 is anchored in the Bitcoin blockchain with OpenTimestamps before the weeks the forecast predicts. Download a record and the .ots proof, then run '
            '<span class="mono">ots verify</span>. A forecast published more than two days after the cutoff is skipped, never backdated.</p></details>')


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--retro", required=True, help="board/results/charts_retro.json: the frozen retrospective results")
    ap.add_argument("--market", help="weekly market tokens from board/chart_data.py --market")
    ap.add_argument("--evaluation", help="runs/openrouter/evaluation.json: the backtest's spend forecasts per window")
    a = ap.parse_args()
    root, out = Path(a.records), Path(a.out)
    (out / "records").mkdir(parents=True, exist_ok=True)
    recs = sorted((root / "openrouter").glob("*.json"))
    sb = json.loads((root.parent / "scoreboard.json").read_text()) if (root.parent / "scoreboard.json").exists() else {"by_horizon": {}, "records": []}
    scored = {r["t0"]: r for r in sb.get("records", [])}
    proofs = []
    for f in recs:
        publish(f, out / "records" / f.name)
        if Path(str(f) + ".ots").exists():
            publish(Path(str(f) + ".ots"), out / "records" / (f.name + ".ots"))
        proofs.append((json.loads(f.read_text()), hashlib.sha256(f.read_bytes()).hexdigest(), f.name))
    retro = accuracy(public(json.loads(Path(a.retro).read_text())))
    sets = retro["sets"]
    market = json.loads(Path(a.market).read_text()) if a.market and Path(a.market).exists() else None
    ev = json.loads(Path(a.evaluation).read_text()) if a.evaluation and Path(a.evaluation).exists() else None
    spend = spend_section(ev) if ev else None
    H = proofs[-1][0]["horizon_weeks"] if proofs else 8
    live = sb.get("by_horizon", {})
    # ---- stat strip
    if "1" in live:
        live_stat = (f'{live["1"]["error_reduction_pct"]:.0f}%', f'less error one week ahead, live ({live["1"]["n_forecasts"]} scored)')
    else:
        first = (date.fromisoformat(proofs[0][0]["t0"]) + timedelta(days=7)) if proofs else next_monday() + timedelta(days=7)
        live_stat = (f'{first:%-d %b}', "first live score lands")
    stats = [(str(len(proofs)) if proofs else f"{next_monday():%-d %b}", ("forecast" if len(proofs) == 1 else "forecasts") + " published in advance" if proofs else "first forecast publishes"), live_stat]
    hm = sets["heldout"]["mean"]
    held_order = sorted(hm, key=lambda k: -hm[k]["mean"])
    if held_order[0] == "combined":
        stats.append((f'{hm["combined"]["mean"]:.1f}%', f'accuracy on held-out weeks, highest of {len(hm)} methods'))
    inner = [HERO, strip(stats)]
    inner.append('<section id="accuracy"><div class="ctl" id="ctl-rank"></div><div class="panel"><div class="dir"><b>Forecast accuracy by method</b><span class="up">Higher is better →</span></div><div id="c-rank"></div></div>'
                 '<p class="sub" style="margin-top:10px">Accuracy is 100% minus token-weighted error across the leading apps. The axis zooms in on the range shown and does not start at zero.</p></section>')
    market_panel = ""
    # ---- market series, with the latest forecast appended
    forecast = None
    if market:
        if proofs:
            latest_rec = proofs[-1][0]
            pairs = [(w, v) for w, v in zip(latest_rec["weeks"], latest_rec["market_tokens"]["simulation"]) if str(w)[:10] > market["weeks"][-1]]
            if pairs:
                forecast = {"weeks": [str(w)[:10] for w, _ in pairs], "tokens": [v for _, v in pairs]}
        multiple = market["tokens"][-1] / market["tokens"][0]
        market_panel = (f'<section><div class="panel"><div class="panel-head"><b>All AI tokens on OpenRouter, per week</b>'
                     f'<span>{multiple:,.0f}× since {long_date(market["weeks"][0])}, latest week {fmt_tokens(market["tokens"][-1])}</span></div><div id="c-market"></div></div></section>')
    # ---- this week's call
    if proofs:
        latest, digest, name = proofs[-1]
        comb = latest.get("cumulative_1_2_4_8", {}).get("combined")
        for i, x in enumerate(latest["apps"]):
            x["total_next"] = comb[i][3] if comb else sum(x["tokens"])
        movers = sorted(((x["total_next"] / (x["recent_weekly_tokens"] * H) - 1, x) for x in latest["apps"]
                         if x["persistence"] == "steady" and x["recent_weekly_tokens"] > 0), key=lambda t: t[0])
        def item(g: float, x: dict) -> str:
            lo, hi = x["tokens_total_range90"]
            return (f'<div class="row"><div><div class="nm">{html.escape(x["name"])}</div><div class="meta">{fmt_tokens(x["total_next"])} tokens next {H} weeks · '
                    f'simulation range {fmt_tokens(lo)}–{fmt_tokens(hi)}</div></div><div><span class="chg {"up" if g >= 0 else "down"}">{g * 100:+.0f}%</span>'
                    f'<button class="cp" onclick="cp(this)" data-t="{html.escape(share_text(x, g, latest, digest))}">Share</button></div></div>')
        made = latest["generated_utc"][:10]
        inner.append(f'<section><h2>This week\'s call</h2><p class="sub">Made {made} for the {H} weeks from {latest["t0"]}. '
                     f'Record <a class="mono" href="records/{name}">{digest[:12]}</a>{" · <a href=records/" + name + ".ots>timestamp proof</a>" if (out / "records" / (name + ".ots")).exists() else ""}</p>'
                     f'<div class="call"><div class="cap">All AI tokens on OpenRouter, next {H} weeks</div><div class="big">{fmt_tokens(sum(latest["market_tokens"]["simulation"]))}</div>'
                     f'<div class="cap">The leading {len(latest["apps"])} apps will spend about <b>${latest["top_spend_total_usd"]["simulation"] / 1e6:,.0f}M</b> at list prices.</div></div>'
                     f'<div class="cols"><div class="list"><h3>Set to grow</h3>{"".join(item(g, x) for g, x in reversed([m for m in movers if m[0] > 0][-8:]))}</div>'
                     f'<div class="list"><h3>Set to shrink</h3>{"".join(item(g, x) for g, x in [m for m in movers if m[0] < 0][:8])}</div></div>'
                     f'<p class="sub" style="margin-top:14px">Change against each app\'s recent pace (the app\'s average week over the four weeks before the cutoff). Established apps only.</p></section>')
    else:
        inner.append(f'<section><h2>This week\'s call</h2><div class="call"><div class="cap">First forecast publishes</div><div class="big">{next_monday():%A %-d %B}</div>'
                     f'<div class="cap">as soon as OpenRouter publishes the week, and never more than two days after the cutoff.</div></div></section>')
    inner.append(market_panel)
    if spend:
        inner.append(spend["html"])
    # ---- live results, once weeks have elapsed
    lm = json.loads((root.parent / "scoreboard_methods.json").read_text()) if (root.parent / "scoreboard_methods.json").exists() else {}
    if lm:
        rows = "".join(f'<tr><td>{h} week{"s" if h != "1" else ""} ahead<div class="meta">{v["n_forecasts"]} live forecasts</div></td><td>{pct(100 - v["combined"])}</td><td>{pct(100 - v["llm"] if "llm" in v else None)}</td>'
                       f'<td>{pct(100 - v[v["best_other"]])}<div class="meta">{LABELS.get(v["best_other"], v["best_other"])}</div></td></tr>' for h, v in lm.items())
        inner.append(f'<section><h2>Live results</h2><p class="sub">Forecasts published in advance and scored as the weeks arrive.</p><div class="tw"><table><tr><th>Horizon</th><th>Our forecast</th><th>Language model alone</th><th>Best other</th></tr>{rows}</table></div></section>')
    # ---- retrospective results: ranked chart, table and text switch together
    copy = set_copy(sets)
    note = {k: ' <span class="meta">(tested later on the same weeks)</span>' for k in ("T3", "T1")}
    blocks = []
    for key, _ in SET_LABELS:
        m = sets[key]["mean"]
        hz = tuple(h for h in ("1", "2", "4", "8") if any(m[k].get(h) is not None for k in m))
        hidden = "" if key == "heldout" else " is-hidden"
        blocks.append(f'<div class="set{hidden}" data-set="{key}"><div class="tw-in">{table(m, sorted(m, key=lambda k: -m[k]["mean"]), hz, "combined", note if key != "backtest" else None)}</div></div>')
    subs = "".join(f'<p class="sub{"" if k == "heldout" else " is-hidden"}" data-set="{k}">{copy[k]}</p>' for k, _ in SET_LABELS)
    inner.append(f'<section id="record"><h2>The full record</h2><div class="ctl" id="ctl-record"></div>{subs}{"".join(blocks)}</section>')
    inner.append('<section><h2>Week by week</h2><p class="sub">Each point is the accuracy at one weekly cutoff; higher is better. The leading methods trade places from week to week, so a small gap in the average is not decisive. '
                 'Move across the chart for every method\'s accuracy, or click a name to hide a line.</p><div class="ctl" id="ctl-weekly"></div><div class="legend" id="leg-weekly"></div>'
                 '<div class="panel"><div id="c-weekly"></div></div><p class="sub" id="note-weekly" style="margin-top:10px"></p>'
                 '<details class="tv"><summary>Table view</summary><div class="tw" id="weekly-table"></div></details></section>')
    inner.append('<section><h2>Forecast against actual</h2><p class="sub">Held-out weeks only. Every dot is one app. Dots on the line were forecast exactly; the further from the line, the bigger the miss. '
                 'Both axes are on a log scale. Apps that fell outside the weekly top 200 are counted at half the 200th app\'s volume, which makes the flat row along the bottom. Switch the method or the week and watch the dots move.</p>'
                 '<div class="ctl" id="ctl-scat-m"></div><div class="ctl" id="ctl-scat-h"></div><div class="ctl" id="ctl-scat-c"></div>'
                 '<div class="panel"><div id="c-scatter"></div></div><p class="sub" id="scat-err" style="margin-top:10px"></p>'
                 '<details class="tv"><summary>Table view</summary><div class="tw" id="scat-table"></div></details></section>')
    # ---- folded detail
    if proofs:
        hist = "".join(
            f'<tr><td>{r["t0"]}</td><td>{scored.get(r["t0"], {}).get("weeks_published", 0)}/{r["horizon_weeks"]}</td>'
            + "".join(f'<td>{pct((lambda e: None if e is None else 100 - e)((scored.get(r["t0"], {}).get("horizons", {}).get(h) or {}).get("company_tokens_wape", {}).get("simulation")))}</td>' for h in ("1", "4", "8"))
            + f'<td class="mono"><a href="records/{n}">{d_[:12]}</a></td></tr>' for r, d_, n in reversed(proofs))
        inner.append(f'<details><summary>Every forecast ({len(proofs)})</summary><div class="tw"><table><tr><th>Cutoff</th><th>Weeks in</th><th>1 wk accuracy</th><th>4 wk</th><th>8 wk</th><th>Record</th></tr>{hist}</table></div></details>')
    inner.append(method_details(H))
    last = market["weeks"][-1] if market else ""
    data = {"retro": {"sets": sets, "weekly": retro["weekly"], "scatter": retro["scatter"]}, "market": market, "forecast": forecast, "labels": LABELS, "inputs": INPUTS,
            "spend": spend["data"] if spend else None, "spend_alt": "Line chart of actual and forecast 8-week spend of the leading apps per backtest window; the table view below lists the values.",
            "set_labels": SET_LABELS, "market_alt": f"Area chart of weekly AI tokens on OpenRouter to {last}.",
            "weekly_alt": "Line chart of each method's accuracy at every weekly cutoff; the table view below lists the values.",
            "scatter_alt": "Scatter chart of forecast against actual tokens per app; the table view below lists the values."}
    built = page("".join(inner), data)
    named = [f.name for f in (out / "records").iterdir() if UNNAMED.search(f.read_text(errors="ignore"))] + (["index.html"] if UNNAMED.search(built) else [])
    if named:
        raise SystemExit(f"refusing to build: the model is named in {named}")
    (out / "index.html").write_text(built)
    print(f"built {out / 'index.html'} from {len(proofs)} records")


def publish(src: Path, dst: Path) -> None:
    """Copy a record or proof next to the page (records are read-only at the source; the copy is replaced each build)."""
    if dst.exists():
        dst.chmod(0o644)
    shutil.copyfile(src, dst)


def next_monday() -> date:
    t = date.today()
    return t + timedelta(days=(7 - t.weekday()) % 7)                  # today on a Monday: the forecast is due that day


def share_text(x: dict, g: float, rec: dict, digest: str) -> str:
    lo, hi = x["tokens_total_range90"]
    return (f"WORKCAST forecast, made {rec['generated_utc'][:10]} before the weeks happened: {x['name']} will use {fmt_tokens(x.get('total_next', sum(x['tokens'])))} tokens on OpenRouter "
            f"over the next {rec['horizon_weeks']} weeks ({g * 100:+.0f}% vs recent pace; 90% range {fmt_tokens(lo)}-{fmt_tokens(hi)}). "
            f"Timestamped record {digest[:12]}. Scored in public: sumervaid.com/predict")


if __name__ == "__main__":
    main()
