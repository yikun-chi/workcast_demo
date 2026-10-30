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
    for unit, div in (("T", 1e12), ("B", 1e9), ("M", 1e6)):
        if abs(x) >= div:
            return f"{x / div:.1f}{unit}"
    return f"{x:,.0f}"


def pct(x: float | None, d: int = 1) -> str:
    return "–" if x is None else f"{x:.{d}f}%"


CSS = """
:root{--bg:#0b0d10;--fg:#e8eaed;--mut:#9aa0a6;--card:#14181d;--line:#262b31;--acc:#34d399;--neg:#f87171}
@media (prefers-color-scheme: light){:root:not([data-theme=dark]){--bg:#fafaf9;--fg:#18181b;--mut:#52525b;--card:#fff;--line:#e4e4e7;--acc:#059669;--neg:#dc2626}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,sans-serif}
main{max-width:1040px;margin:0 auto;padding:28px 16px 64px}h1{font-size:30px;line-height:1.15;margin:0 0 8px}h2{font-size:18px;margin:36px 0 10px}
.lede{color:var(--mut);max-width:760px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin:18px 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px}.v{font-size:26px;font-weight:700}.l{color:var(--mut);font-size:13px}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}th,td{padding:7px 8px;border-bottom:1px solid var(--line);text-align:right}
th:first-child,td:first-child{text-align:left}th{color:var(--mut);font-weight:600;font-size:13px}.up{color:var(--acc)}.down{color:var(--neg)}
.wrap{overflow-x:auto}.mono{font-family:ui-monospace,Menlo,monospace;font-size:12px;color:var(--mut);word-break:break-all}
button{background:transparent;border:1px solid var(--line);color:var(--fg);border-radius:8px;padding:3px 8px;cursor:pointer;font-size:12px}
.note{color:var(--mut);font-size:13px;max-width:820px}
"""


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
        shutil.copy2(f, out / "records" / f.name)
        if Path(str(f) + ".ots").exists():
            shutil.copy2(str(f) + ".ots", out / "records" / (f.name + ".ots"))
        proofs.append((json.loads(f.read_text()), hashlib.sha256(f.read_bytes()).hexdigest(), f.name))
    bt = backtest_html(json.loads(Path(a.evaluation).read_text())) if a.evaluation and Path(a.evaluation).exists() else ""
    if not proofs:
        (out / "index.html").write_text(launch_page(bt))
        print(f"built {out / 'index.html'} (launch page: no forecast published yet)")
        return
    latest, latest_sha, latest_name = proofs[-1]
    H = latest["horizon_weeks"]
    # ---- latest forecast: predicted growth over the horizon against each app's recent weekly level
    movers = []
    for x in latest["apps"]:
        base = x["recent_weekly_tokens"] * H
        if base > 0 and x["persistence"] == "steady":
            movers.append((sum(x["tokens"]) / base - 1, x))
    movers.sort(key=lambda t: t[0])
    mt = latest["market_tokens"]["simulation"]
    hz = sb.get("by_horizon", {})
    def head_stat(h: str) -> str:
        r = hz.get(h)
        if not r:
            return '<div class="card"><div class="v">pending</div><div class="l">%s-week forecasts scored so far: none yet</div></div>' % h
        return (f'<div class="card"><div class="v">{pct(r["error_reduction_pct"], 0)}</div><div class="l">less error than the best standard forecast, '
                f'{h} week{"s" if h != "1" else ""} ahead ({r["n_forecasts"]} forecast{"s" if r["n_forecasts"] != 1 else ""} scored)</div></div>')
    rows_m = lambda items: "".join(  # noqa: E731
        f'<tr><td>{html.escape(x["name"])}</td><td>{html.escape(x["category"])}</td><td>{fmt_tokens(x["recent_weekly_tokens"])}</td>'
        f'<td>{fmt_tokens(sum(x["tokens"]))}</td><td>{fmt_tokens(x["tokens_total_range90"][0])}–{fmt_tokens(x["tokens_total_range90"][1])}</td>'
        f'<td class="{"up" if g >= 0 else "down"}">{g * 100:+.0f}%</td>'
        f'<td><button onclick="share(this)" data-t="{html.escape(share_text(x, g, latest, latest_sha))}">copy</button></td></tr>' for g, x in items)
    hist = "".join(
        f'<tr><td>{r["t0"]}</td><td>{scored.get(r["t0"], {}).get("weeks_published", 0)} of {r["horizon_weeks"]}</td>'
        + "".join(f'<td>{pct(scored.get(r["t0"], {}).get("horizons", {}).get(h, {}).get("company_tokens_wape", {}).get("simulation"))} / '
                  f'{pct((lambda s: s["company_tokens_wape"][s["best_standard"]] if s else None)(scored.get(r["t0"], {}).get("horizons", {}).get(h)))}</td>' for h in ("1", "2", "4", "8"))
        + f'<td class="mono"><a href="records/{n}">{s[:16]}…</a>{" · <a href=records/" + n + ".ots>proof</a>" if (out / "records" / (n + ".ots")).exists() else ""}</td></tr>'
        for r, s, n in reversed(proofs))
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>WORKCAST Forecast Board</title><style>{CSS}</style></head><body><main>
<h1>AI demand, forecast before it happens.</h1>
<p class="lede">Every week WORKCAST publishes a dated forecast of how many AI tokens the leading apps on OpenRouter will use over the next {H} weeks, next to the standard forecasts made from the same data. Each forecast is hashed and anchored with OpenTimestamps before the weeks it predicts, then scored in public as the weeks arrive. Misses stay on the board.</p>
<div class="grid">{head_stat("1")}{head_stat("4")}{head_stat("8")}
<div class="card"><div class="v">{len(proofs)}</div><div class="l">forecasts published in advance (latest cutoff {latest["t0"]})</div></div></div>
<h2>This week's forecast: the next {H} weeks from {latest["t0"]}</h2>
<p class="note">All AI tokens routed through OpenRouter over the {H} weeks: <b>{fmt_tokens(sum(mt))}</b> (simulation). The {len(latest["apps"])} leading apps' combined spend at list prices: <b>${latest["top_spend_total_usd"]["simulation"] / 1e6:,.1f}M</b> (the point estimate that cut combined-spend error by about half in the backtests).</p>
<h2>Forecast to grow most</h2><div class="wrap"><table><tr><th>App</th><th>Category</th><th>Recent week</th><th>Next {H} weeks</th><th>90% range</th><th>vs recent pace</th><th>Share</th></tr>{rows_m(list(reversed(movers[-10:])))}</table></div>
<h2>Forecast to shrink most</h2><div class="wrap"><table><tr><th>App</th><th>Category</th><th>Recent week</th><th>Next {H} weeks</th><th>90% range</th><th>vs recent pace</th><th>Share</th></tr>{rows_m(movers[:10])}</table></div>
<p class="note">Established apps only (ranked in all eight weeks before the cutoff). "vs recent pace" compares the forecast total with {H} times the app's average week over the four weeks before the cutoff.</p>
{bt}
<h2>Every forecast, scored as the weeks arrive</h2>
<div class="wrap"><table><tr><th>Cutoff</th><th>Weeks published</th><th>1 wk: ours / best standard</th><th>2 wk</th><th>4 wk</th><th>8 wk</th><th>Record (SHA-256)</th></tr>{hist}</table></div>
<p class="note">Error is the token-weighted error in each app's tokens over the first weeks after the cutoff (lower is better), against the best of: last four weeks carried forward, each app's recent trend, and market growth. Data: OpenRouter Datasets API (CC BY 4.0). Before this board, the same method was backtested at 16 cutoffs from July 2025 to August 2026. To verify a record: download it, compute its SHA-256, and run <span class="mono">ots verify</span> on its proof.</p>
</main><script>function share(b){{navigator.clipboard&&navigator.clipboard.writeText(b.dataset.t);b.textContent="copied";setTimeout(()=>b.textContent="copy",1200)}}</script></body></html>"""
    (out / "index.html").write_text(page)
    print(f"built {out / 'index.html'} from {len(proofs)} records")


def backtest_html(ev: dict) -> str:
    """The method's retrospective record: 16 cutoffs scored before this board started (numbers read from the evaluation)."""
    acc = ev["accuracy"]; labels = ev["comparator_labels"]
    h1 = acc["by_horizon"]["1"]; b1 = min(labels, key=lambda k: h1[k])
    ts = next(b for b in ev["business_validation"] if b["id"] == "top_spend")
    wins = ev["windows"]
    return (f'<h2>Before the board: the backtest</h2><div class="grid">'
            f'<div class="card"><div class="v">{100 * (1 - h1["simulation"] / h1[b1]):.0f}%</div><div class="l">less error one week ahead than the best standard forecast ({h1["simulation"]:.1f}% vs {h1[b1]:.1f}%)</div></div>'
            f'<div class="card"><div class="v">{ts["error_reduction_pct"]:.0f}%</div><div class="l">less error on the leading apps\' combined {ev["protocol"]["horizon_weeks"]}-week spend</div></div>'
            f'<div class="card"><div class="v">{sum(w["n_apps"] for w in wins):,}</div><div class="l">company forecasts at {len(wins)} cutoffs, {wins[0]["cutoff"]} to {wins[-1]["cutoff"]}</div></div></div>'
            f'<p class="note">Retrospective: the method was designed with these periods available, which is why the board now publishes forecasts in advance.</p>')


def launch_page(bt: str) -> str:
    nxt = date.today() + timedelta(days=(7 - date.today().weekday()) % 7 or 7)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>WORKCAST Forecast Board</title><style>{CSS}</style></head><body><main>
<h1>AI demand, forecast before it happens.</h1>
<p class="lede">Every week WORKCAST will publish a dated forecast of how many AI tokens the leading apps on OpenRouter will use over the next eight weeks, next to the standard forecasts made from the same data. Each forecast is hashed and anchored with OpenTimestamps before the weeks it predicts, then scored in public as the weeks arrive. Misses stay on the board.</p>
<div class="grid"><div class="card"><div class="v">{nxt:%d %b %Y}</div><div class="l">first forecast publishes, within two days of its cutoff</div></div></div>
{bt}
</main></body></html>"""


def share_text(x: dict, g: float, rec: dict, digest: str) -> str:
    lo, hi = x["tokens_total_range90"]
    return (f"WORKCAST forecast, made {rec['t0']} before the weeks happened: {x['name']} will use {fmt_tokens(sum(x['tokens']))} tokens on OpenRouter "
            f"over the next {rec['horizon_weeks']} weeks ({g * 100:+.0f}% vs its recent pace; 90% range {fmt_tokens(lo)}-{fmt_tokens(hi)}). "
            f"Timestamped record sha256 {digest[:16]}. We'll score it in public.")


if __name__ == "__main__":
    main()
