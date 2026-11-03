"""GPT-6 Astra against WORKCAST on the OpenRouter windows that start after Astra's knowledge cutoff (30 April 2026).

Protocol: docs/plans/astra_forecast_protocol.md, "Run 1" (frozen before any call). At each cutoff Astra sees the same
100 apps WORKCAST forecast, with each app's weekly tokens for the 12 weeks before the cutoff and the market total, and
returns each app's cumulative tokens over the first 1, 2, 4 and 8 weeks. Two samples per cutoff; the forecast is their
mean. Scored with the board's metric on the same actuals, next to WORKCAST and the standard forecasts at the same
cutoffs (read from runs/openrouter/evaluation.json). Every response is cached with its token usage and cost; the run
stops before a call that could pass the cap.

    OPENAI_API_KEY=... .venv/bin/python board/astra_backtest.py --out /Volumes/PsychDynamicsData/workcast_board/astra --cap-usd 25
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

from orgsim.instances import get_instance
from orgsim.worlds import market as M

MODEL = "gpt-6-astra"
KNOWLEDGE_CUTOFF = pd.Timestamp("2026-04-30")      # OpenAI models page, checked 2026-10-30
PRICE = {"input": 10.0, "output": 50.0}            # USD per million tokens, same page
HORIZONS = (1, 2, 4, 8)
SAMPLES = 2
HISTORY = 12
WORST_CALL_USD = 2.5                               # 40k output tokens + 20k input, the most one call can cost here
SYSTEM = ("You are a forecaster. You forecast weekly AI token usage of apps on OpenRouter from their recent history. "
          "Give your best point forecast for each app. Reply with JSON only.")


def prompt(d: M.MarketData, t0: pd.Timestamp, ids: list[int]) -> str:
    hist = [t0 - (HISTORY - i) * M.WEEK for i in range(HISTORY)]
    x, cens = M.app_matrix(d, hist, ids)
    meta = d.apps.set_index("app_id").reindex(ids)
    mk = d.mw.groupby("week").market_tokens.first().reindex(hist)
    lines = [f"Today is {t0.date()}. Below is weekly token usage (billions of tokens, Monday-Sunday weeks) for {len(ids)} apps on OpenRouter, "
             f"for the {HISTORY} weeks ending {(t0 - pd.Timedelta(days=1)).date()}. 'out' means the app was outside OpenRouter's weekly top 200 that week.",
             "", "Market total, all apps (billions): " + ", ".join(f"{v / 1e9:.0f}" for v in mk.to_numpy()), "",
             "id | app | category | " + " | ".join(str(w.date()) for w in hist)]
    for i, aid in enumerate(ids):
        cells = ["out" if cens[i, j] else f"{x[i, j] / 1e9:.1f}" for j in range(HISTORY)]
        lines.append(f"{aid} | {meta.iloc[i].get('app_name', aid)} | {meta.iloc[i].get('category', '')} | " + " | ".join(cells))
    lines += ["", "For every app, forecast its cumulative tokens (billions) over the first 1, 2, 4 and 8 weeks starting today, counting weeks "
              "outside the top 200 at the volume you expect. Respond as JSON: {\"forecasts\": {\"<id>\": [w1, w1_2, w1_4, w1_8], ...}}."]
    return "\n".join(lines)


def call(user: str, sample: int, cache: Path, ledger: list[dict], cap: float) -> dict:
    body = {"model": MODEL, "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
            "response_format": {"type": "json_object"}, "reasoning_effort": "medium", "max_completion_tokens": 40000, "seed": sample}
    key = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    path = cache / f"{key}.json"
    if path.exists():
        return json.loads(path.read_text())
    spent = sum(r["usd"] for r in ledger)
    if spent + WORST_CALL_USD > cap:
        raise SystemExit(f"stop: ${spent:.2f} spent; another call could pass the ${cap:.0f} cap")
    for attempt in range(4):
        r = httpx.post("https://api.openai.com/v1/chat/completions", json=body, timeout=900,
                       headers={"authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"})
        if r.status_code in (429, 500, 502, 503) and attempt < 3:
            time.sleep(20 * (attempt + 1)); continue
        if r.status_code != 200:
            raise SystemExit(f"HTTP {r.status_code}: {r.text[:400]}")
        break
    out = r.json()
    u = out.get("usage", {})
    usd = (u.get("prompt_tokens", 0) * PRICE["input"] + u.get("completion_tokens", 0) * PRICE["output"]) / 1e6
    rec = {"request_sha256": key, "model": out.get("model"), "system_fingerprint": out.get("system_fingerprint"), "created": out.get("created"),
           "usage": u, "usd": usd, "request": body, "text": out["choices"][0]["message"]["content"]}
    path.write_text(json.dumps(rec))
    ledger.append({"request_sha256": key, "usd": usd, "utc": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    print(f"  call {key[:10]} model={rec['model']} tokens in={u.get('prompt_tokens')} out={u.get('completion_tokens')} ${usd:.3f} (total ${sum(r_['usd'] for r_ in ledger):.2f})", flush=True)
    return rec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--cap-usd", type=float, required=True)
    ap.add_argument("--limit-calls", type=int, default=0, help="stop after this many new calls (0 = no limit); for a first test call")
    a = ap.parse_args()
    out = Path(a.out); cache = out / "responses"; cache.mkdir(parents=True, exist_ok=True)
    ledger_path = out / "ledger.json"
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else []
    ctx = get_instance("openrouter")
    d = M.load_data(ctx)
    ev = json.loads((ctx.runs_dir / "evaluation.json").read_text())
    proto = ctx.yaml("evaluation/protocol.yaml")
    n_apps = int(proto.get("n_apps", ctx.yaml("calibration/market.yaml").get("n_apps", 100))) if "n_apps" in proto else 100
    cutoffs = [pd.Timestamp(c) for c in proto["cutoffs"] if pd.Timestamp(c) > KNOWLEDGE_CUTOFF]
    rows, new_calls = [], 0
    for c in cutoffs:
        ids = M.top_apps(d, c, n_apps)
        user = prompt(d, c, ids)
        preds = []
        for s in range(1, SAMPLES + 1):
            before = len(ledger)
            rec = call(user, s, cache, ledger, a.cap_usd)
            new_calls += len(ledger) - before
            ledger_path.write_text(json.dumps(ledger, indent=1))
            f = json.loads(rec["text"])["forecasts"]
            preds.append(np.array([[float(f.get(str(i), [np.nan] * 4)[k]) for k in range(4)] for i in ids]) * 1e9)
            if a.limit_calls and new_calls >= a.limit_calls:
                print("stopping after the test call"); return
        P = np.nanmean(np.stack(preds), axis=0)                       # apps x 4 cumulative forecasts
        missing = int(np.isnan(P).any(1).sum())
        y, _ = M.app_matrix(d, [c + i * M.WEEK for i in range(max(HORIZONS))], ids)
        win = next(w for w in ev["windows"] if w["cutoff"] == str(c.date()))
        hz = {}
        for k, h in enumerate(HORIZONS):
            act = y[:, :h].sum(1)
            ok = ~np.isnan(P[:, k])
            hz[str(h)] = {"astra": M.wape(P[ok, k], act[ok]), **win["by_horizon"][str(h)]}
        rows.append({"cutoff": str(c.date()), "apps_missing_from_answer": missing, "by_horizon": hz,
                     "sample_spread_pct": float(np.nanmean(np.abs(preds[0][:, 3] - preds[-1][:, 3]) / np.maximum(P[:, 3], 1)) * 100)})
        print(c.date(), {h: {k: round(v, 1) for k, v in r.items()} for h, r in hz.items()}, flush=True)
    who = list(rows[0]["by_horizon"]["1"])
    agg = {h: {k: float(np.mean([r["by_horizon"][h][k] for r in rows])) for k in who} for h in map(str, HORIZONS)}
    res = {"model": MODEL, "knowledge_cutoff": str(KNOWLEDGE_CUTOFF.date()), "cutoffs": [r["cutoff"] for r in rows], "samples": SAMPLES,
           "spent_usd": sum(r["usd"] for r in ledger), "calls": len(ledger), "by_horizon": agg, "windows": rows,
           "comparator_labels": ev["comparator_labels"], "protocol": "docs/plans/astra_forecast_protocol.md, Run 1"}
    (out / "results.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(agg, indent=1)); print(f"spent ${res['spent_usd']:.2f} over {res['calls']} calls")


if __name__ == "__main__":
    main()
