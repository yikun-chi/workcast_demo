"""Build the public forecast board (one static page) from the records, their timestamp proofs and the scoreboard.

Every number on the page is read from a record or from scoreboard.json; nothing is typed in. Records and proofs are
copied next to the page so anyone can re-hash a forecast and verify its timestamp with `ots verify`.

    .venv/bin/python board/build_site.py --records /Volumes/PsychDynamicsData/workcast_board/records --out /Volumes/PsychDynamicsData/workcast_board/site
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import shutil
from datetime import date, timedelta
from pathlib import Path


def fmt_tokens(x: float) -> str:
    if abs(x) >= 1e15:
        return f"{x / 1e12:,.0f}T"
    for unit, div in (("T", 1e12), ("B", 1e9), ("M", 1e6)):
        if abs(x) >= div:
            return f"{x / div:.1f}{unit}"
    return f"{x:,.0f}"


def pct(x: float | None, d: int = 1) -> str:
    return "–" if x is None else f"{x:.{d}f}%"


CSS = """
:root{--bg:#fbfbf9;--fg:#111316;--mut:#6b7078;--soft:#f1f2ee;--line:#e6e7e2;--acc:#0f9f6e;--acc-soft:#e3f5ed;--neg:#d4493f;--neg-soft:#fbe9e7;--bar:#c9ccc6}
@media (prefers-color-scheme: dark){:root:not([data-theme=light]){--bg:#0c0e10;--fg:#eceee9;--mut:#8d939a;--soft:#15181b;--line:#23272b;--acc:#34d399;--acc-soft:#0f2a20;--neg:#f2766b;--neg-soft:#2c1614;--bar:#3a4046}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 ui-sans-serif,-apple-system,BlinkMacSystemFont,"Inter","Segoe UI",sans-serif;-webkit-font-smoothing:antialiased}
main{max-width:920px;margin:0 auto;padding:56px 16px 96px}
.kicker{font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:var(--mut);font-weight:600}
h1{font-size:clamp(34px,6vw,54px);line-height:1.04;letter-spacing:-.025em;margin:12px 0 16px;font-weight:750}
.lede{font-size:18px;color:var(--mut);max-width:640px;margin:0}
.strip{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:var(--line);border:1px solid var(--line);border-radius:16px;overflow:hidden;margin:40px 0 56px}
.strip>div{background:var(--bg);padding:20px}.big{font-size:32px;font-weight:720;letter-spacing:-.02em;font-variant-numeric:tabular-nums}.cap{font-size:13px;color:var(--mut);margin-top:2px}
h2{font-size:22px;letter-spacing:-.01em;margin:0 0 4px}.sub{color:var(--mut);font-size:14px;margin:0 0 20px}
section{margin:0 0 64px}
.call{background:var(--soft);border-radius:20px;padding:28px}.call .big{font-size:clamp(40px,7vw,60px)}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:28px;margin-top:28px}
.list h3{font-size:14px;color:var(--mut);font-weight:600;margin:0 0 6px;text-transform:uppercase;letter-spacing:.06em}
.row{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:11px 0;border-bottom:1px solid var(--line)}
.row:last-child{border-bottom:0}.nm{font-weight:600}.meta{font-size:13px;color:var(--mut)}
.pill{font-size:14px;font-weight:650;padding:3px 10px;border-radius:999px;font-variant-numeric:tabular-nums;white-space:nowrap}
.up{background:var(--acc-soft);color:var(--acc)}.down{background:var(--neg-soft);color:var(--neg)}
.cp{border:0;background:none;color:var(--mut);cursor:pointer;font-size:13px;padding:0;margin-left:8px}.cp:hover{color:var(--fg)}
.bars{display:grid;gap:18px}.hz{display:grid;grid-template-columns:110px 1fr;gap:14px;align-items:center}
.hz .lab{font-size:14px;font-weight:600}.hz .lab span{display:block;font-weight:400;color:var(--mut);font-size:12px}
.b{display:flex;align-items:center;gap:10px;white-space:nowrap;font-size:13px;color:var(--mut);font-variant-numeric:tabular-nums}
.b i{display:block;height:10px;border-radius:6px;background:var(--bar)}.b.us i{background:var(--acc)}.b.us{color:var(--fg);font-weight:600}
.legend{display:flex;gap:18px;font-size:13px;color:var(--mut);margin:0 0 18px}.legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;vertical-align:-1px}
details{border-top:1px solid var(--line);padding:16px 0}details:last-of-type{border-bottom:1px solid var(--line)}
summary{cursor:pointer;font-weight:600;list-style:none}summary::-webkit-details-marker{display:none}summary:after{content:"+";float:right;color:var(--mut)}details[open] summary:after{content:"–"}
details p,details li{color:var(--mut);font-size:14px}
table{width:100%;border-collapse:collapse;font-size:14px;font-variant-numeric:tabular-nums;margin-top:12px}th,td{padding:8px 6px;border-bottom:1px solid var(--line);text-align:right}
th:first-child,td:first-child{text-align:left}th{color:var(--mut);font-weight:600;font-size:12px}
.mono{font-family:ui-monospace,Menlo,monospace;font-size:12px}a{color:inherit}
footer{color:var(--mut);font-size:13px;margin-top:48px}
@media (max-width:700px){.strip{grid-template-columns:1fr}.cols{grid-template-columns:1fr}.hz{grid-template-columns:1fr;gap:6px}main{padding-top:36px}}
"""


def page(inner: str) -> str:
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>Forecast Board · WORKCAST</title><meta name="description" content="Dated, timestamped forecasts of AI demand, scored in public.">'
            f'<style>{CSS}</style></head><body><main>{inner}<footer>WORKCAST by Sumer Vaid · Data: OpenRouter Datasets API (CC BY 4.0)</footer></main>'
            '<script>function cp(b){navigator.clipboard&&navigator.clipboard.writeText(b.dataset.t);b.textContent="Copied";setTimeout(()=>b.textContent="Share",1400)}</script></body></html>')


HERO = ('<div class="kicker">WORKCAST · Forecast board</div><h1>AI demand,<br>forecast before it happens.</h1>'
        '<p class="lede">Every week we publish a dated, tamper-proof forecast of how much AI the leading apps will use over the next eight weeks, then score it in public against the standard forecasts. Misses stay up.</p>')


def strip(stats: list[tuple[str, str]]) -> str:
    return '<div class="strip">' + "".join(f'<div><div class="big">{v}</div><div class="cap">{c}</div></div>' for v, c in stats) + "</div>"


def bars(rows: list[tuple[str, str, float, float]]) -> str:
    """Paired bars per horizon: our error and the best standard forecast's error (shorter is better)."""
    top = (max(max(r[2], r[3]) for r in rows) or 1) / 0.78            # longest bar at 78% leaves room for its label
    out = ['<div class="legend"><span><i style="background:var(--acc)"></i>WORKCAST</span><span><i style="background:var(--bar)"></i>Best standard forecast</span></div><div class="bars">']
    for lab, sub, ours, std in rows:
        out.append(f'<div class="hz"><div class="lab">{lab}<span>{sub}</span></div><div>'
                   f'<div class="b us"><i style="width:{ours / top * 100:.1f}%"></i>{ours:.1f}% error</div>'
                   f'<div class="b"><i style="width:{std / top * 100:.1f}%"></i>{std:.1f}%</div></div></div>')
    return "".join(out) + "</div>"


def backtest(ev: dict) -> tuple[list[tuple[str, str, float, float]], dict]:
    acc, labels = ev["accuracy"], ev["comparator_labels"]
    rows = []
    for h, v in acc["by_horizon"].items():
        best = min(labels, key=lambda k: v[k])
        rows.append((f'{h} week{"s" if h != "1" else ""} ahead', f'best: {labels[best].split(":")[0].lower()}', v["simulation"], v[best]))
    ts = next(b for b in ev["business_validation"] if b["id"] == "top_spend")
    h1 = acc["by_horizon"]["1"]
    facts = {"one_week": 100 * (1 - h1["simulation"] / min(h1[k] for k in labels)), "spend": ts["error_reduction_pct"],
             "n": sum(w["n_apps"] for w in ev["windows"]), "cutoffs": len(ev["windows"]), "first": ev["windows"][0]["cutoff"], "last": ev["windows"][-1]["cutoff"]}
    return rows, facts


def method_details(H: int) -> str:
    return (f'<details><summary>How it works</summary><p>At each Monday cutoff, WORKCAST carries every leading app forward {H} weeks from data before the cutoff: '
            'its growth path, whether it stays among the leaders, and the models its workloads move to as new models launch and prices change. '
            'The point forecast is the simulation\'s central path; the range is the 5th to 95th percentile of 20 runs. Standard forecasts are made from the same data: '
            'the last four weeks carried forward, each app\'s recent trend, and market growth. Error is token-weighted across apps (lower is better).</p></details>'
            '<details><summary>How to verify a forecast</summary><p>Each forecast is a read-only JSON record carrying the code version and a hash of every input table. '
            'Its SHA-256 is anchored in the Bitcoin blockchain with OpenTimestamps before the weeks it predicts. Download a record and its .ots proof, then run '
            '<span class="mono">ots verify</span>. A forecast published more than two days after its cutoff is skipped, never backdated.</p></details>')


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--evaluation", help="runs/openrouter/evaluation.json: the backtest record shown beside the live forecasts")
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
    ev = json.loads(Path(a.evaluation).read_text()) if a.evaluation and Path(a.evaluation).exists() else None
    bt_rows, bt = backtest(ev) if ev else ([], {})
    H = proofs[-1][0]["horizon_weeks"] if proofs else 8
    live = sb.get("by_horizon", {})
    # ---- stat strip
    if "1" in live:
        live_stat = (f'{live["1"]["error_reduction_pct"]:.0f}%', f'less error one week ahead, live ({live["1"]["n_forecasts"]} scored)')
    else:
        first = (date.fromisoformat(proofs[0][0]["t0"]) + timedelta(days=7)) if proofs else next_monday() + timedelta(days=7)
        live_stat = (f'{first:%-d %b}', "first live score lands")
    stats = [(str(len(proofs)) if proofs else f"{next_monday():%-d %b}", "forecasts published in advance" if proofs else "first forecast publishes"), live_stat]
    if bt:
        stats.append((f'{bt["one_week"]:.0f}%', f'less error one week ahead in the backtest ({bt["n"]:,} forecasts)'))
    inner = [HERO, strip(stats)]
    # ---- this week's call
    if proofs:
        latest, digest, name = proofs[-1]
        movers = sorted(((sum(x["tokens"]) / (x["recent_weekly_tokens"] * H) - 1, x) for x in latest["apps"]
                         if x["persistence"] == "steady" and x["recent_weekly_tokens"] > 0), key=lambda t: t[0])
        def item(g: float, x: dict) -> str:
            lo, hi = x["tokens_total_range90"]
            return (f'<div class="row"><div><div class="nm">{html.escape(x["name"])}</div><div class="meta">{fmt_tokens(sum(x["tokens"]))} tokens next {H} weeks · '
                    f'range {fmt_tokens(lo)}–{fmt_tokens(hi)}</div></div><div><span class="pill {"up" if g >= 0 else "down"}">{g * 100:+.0f}%</span>'
                    f'<button class="cp" onclick="cp(this)" data-t="{html.escape(share_text(x, g, latest, digest))}">Share</button></div></div>')
        made = latest["generated_utc"][:10]
        inner.append(f'<section><h2>This week\'s call</h2><p class="sub">Made {made} for the {H} weeks from {latest["t0"]}. '
                     f'Record <a class="mono" href="records/{name}">{digest[:12]}</a>{" · <a href=records/" + name + ".ots>timestamp proof</a>" if (out / "records" / (name + ".ots")).exists() else ""}</p>'
                     f'<div class="call"><div class="cap">All AI tokens on OpenRouter, next {H} weeks</div><div class="big">{fmt_tokens(sum(latest["market_tokens"]["simulation"]))}</div>'
                     f'<div class="cap">The leading {len(latest["apps"])} apps will spend about <b>${latest["top_spend_total_usd"]["simulation"] / 1e6:,.0f}M</b> at list prices.</div></div>'
                     f'<div class="cols"><div class="list"><h3>Set to grow</h3>{"".join(item(g, x) for g, x in reversed([m for m in movers if m[0] > 0][-8:]))}</div>'
                     f'<div class="list"><h3>Set to shrink</h3>{"".join(item(g, x) for g, x in [m for m in movers if m[0] < 0][:8])}</div></div>'
                     f'<p class="sub" style="margin-top:14px">Change against each app\'s recent pace (its average week over the four weeks before the cutoff). Established apps only.</p></section>')
    else:
        inner.append(f'<section><h2>This week\'s call</h2><div class="call"><div class="cap">First forecast publishes</div><div class="big">{next_monday():%A %-d %B}</div>'
                     f'<div class="cap">as soon as OpenRouter publishes the week, and never more than two days after its cutoff.</div></div></section>')
    # ---- track record
    tr = ['<section><h2>Track record</h2>']
    if live:
        rows = [(f'{h} week{"s" if h != "1" else ""} ahead', f'{v["n_forecasts"]} live forecast{"s" if v["n_forecasts"] != 1 else ""}', v["simulation"], v[v["best_standard"]]) for h, v in live.items()]
        tr.append(f'<p class="sub">Live forecasts, scored as the weeks arrive.</p>{bars(rows)}')
    if bt_rows:
        tr.append(f'<p class="sub" style="margin-top:28px">Backtest before the board: {bt["n"]:,} company forecasts at {bt["cutoffs"]} cutoffs, {bt["first"]} to {bt["last"]}. '
                  f'Retrospective, which is why we now publish in advance.</p>{bars(bt_rows)}')
    inner.append("".join(tr) + "</section>")
    # ---- folded detail
    if proofs:
        hist = "".join(
            f'<tr><td>{r["t0"]}</td><td>{scored.get(r["t0"], {}).get("weeks_published", 0)}/{r["horizon_weeks"]}</td>'
            + "".join(f'<td>{pct((scored.get(r["t0"], {}).get("horizons", {}).get(h) or {}).get("company_tokens_wape", {}).get("simulation"))}</td>' for h in ("1", "4", "8"))
            + f'<td class="mono"><a href="records/{n}">{d_[:12]}</a></td></tr>' for r, d_, n in reversed(proofs))
        inner.append(f'<details><summary>Every forecast ({len(proofs)})</summary><table><tr><th>Cutoff</th><th>Weeks in</th><th>1 wk error</th><th>4 wk</th><th>8 wk</th><th>Record</th></tr>{hist}</table></details>')
    inner.append(method_details(H))
    (out / "index.html").write_text(page("".join(inner)))
    print(f"built {out / 'index.html'} from {len(proofs)} records")


def publish(src: Path, dst: Path) -> None:
    """Copy a record or proof next to the page (records are read-only at the source; the copy is replaced each build)."""
    if dst.exists():
        dst.chmod(0o644)
    shutil.copyfile(src, dst)


def next_monday() -> date:
    t = date.today()
    return t + timedelta(days=(7 - t.weekday()) % 7 or 7)


def share_text(x: dict, g: float, rec: dict, digest: str) -> str:
    lo, hi = x["tokens_total_range90"]
    return (f"WORKCAST forecast, made {rec['generated_utc'][:10]} before the weeks happened: {x['name']} will use {fmt_tokens(sum(x['tokens']))} tokens on OpenRouter "
            f"over the next {rec['horizon_weeks']} weeks ({g * 100:+.0f}% vs its recent pace; 90% range {fmt_tokens(lo)}-{fmt_tokens(hi)}). "
            f"Timestamped record {digest[:12]}. Scored in public: sumervaid.com/predict")


if __name__ == "__main__":
    main()
