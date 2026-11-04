#!/usr/bin/env python3
"""Plan 02, script 03: the bill as a function of the cache rate, at published prices and token mixes.

Purpose : implements the cache lever in plan_02_levers_to_half.md. No data beyond the price snapshot
          and the session-cost file is read.
Inputs  : inputs_openrouter/models_2026-11-03.json (beside this script)
          --data <instances/openrouter/data> for raw/session_cost/2026-10-27/*.json
Outputs : results_02_20261103/cache_curve.csv, cache_savings.csv, cache_session_growth.csv
Author  : Claude Code for Sumer Vaid, 2026-11-03
Usage   : python 03_cache_lever.py --data /path/to/instances/openrouter/data
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / 'results_02_20261103'
MODELS = ['anthropic/claude-sonnet-5.5', 'anthropic/claude-opus-5.5', 'anthropic/claude-fable-5.1',
          'openai/gpt-6-luna', 'openai/gpt-6.1-sol', 'google/gemini-3.8-flash', 'deepseek/deepseek-v4.1-flash']
# Token mixes from Inferred 03 (sources_02.md): eligible prompt, novel prompt, output. Plan 02 fixes both.
MIX = {'agent': (0.87, 0.12, 0.01), 'human': (0.50, 0.38, 0.12)}
STARTS = [0.44, 0.60, 0.70]
ENDS = [0.88, 0.90]


def prices(snapshot):
    """Per-million prices for each plan model: input, cache read, cache write (5 min), output."""
    by_id = {m['id']: m['pricing'] for m in snapshot['data']}
    rows = []
    for mid in MODELS:
        p = by_id[mid]
        inp = float(p['prompt']) * 1e6
        rows.append({'model': mid, 'input': inp, 'cache_read': float(p['input_cache_read']) * 1e6,
                     # DeepSeek lists no write price (its docs charge writes at the input price) and Gemini lists
                     # a storage rate per hour under that key, so a write is never charged below the input price.
                     'cache_write': max(float(p.get('input_cache_write', p['prompt'])), float(p['prompt'])) * 1e6,
                     'output': float(p['completion']) * 1e6})
    return pd.DataFrame(rows).set_index('model')


def bill(p, mix, c):
    """Dollars per million tokens. c is the cache rate: cache reads over all prompt tokens.
    Every prompt token that is not a read is charged as a cache write, which overstates cost (plan 02)."""
    eligible, novel, out = mix
    prompt = eligible + novel
    reads = min(c, eligible / prompt) * prompt
    return reads * p.cache_read + (prompt - reads) * p.cache_write + out * p.output


def session_growth(data):
    """Log-log slope of median session cost against turns. Near 1 means linear growth (cached prefix),
    near 2 means quadratic growth (the whole context re-billed every turn)."""
    rows = []
    for f in sorted((data / 'raw/session_cost/2026-10-27').glob('*.json')):
        rows += json.load(open(f))['data']
    d = pd.DataFrame(rows).drop_duplicates()
    mid = {'1-turn': 1, '2-9-turns': 5, '10-49-turns': 25, '50-plus-turns': 80}  # Plan 02: fixed midpoints.
    d['turns'] = d.turn_range.map(mid)
    out = []
    for (app, model), g in d.groupby(['app_slug', 'model_permaslug']):
        if g.turns.nunique() < 4:
            continue
        slope = np.polyfit(np.log(g.turns), np.log(g.median_session_cost_usd), 1)[0]
        out.append({'app': app, 'model': model, 'loglog_slope': slope})
    return pd.DataFrame(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', required=True, type=Path)
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    p = prices(json.load(open(HERE / 'inputs_openrouter/models_2026-11-03.json')))
    p.to_csv(OUT / 'cache_prices_used.csv')

    curve, savings = [], []
    for mid, pr in p.iterrows():
        for mix_name, mix in MIX.items():
            for c in np.round(np.arange(0, 0.951, 0.05), 2):
                curve.append({'model': mid, 'mix': mix_name, 'cache_rate': c, 'usd_per_mtok': bill(pr, mix, c)})
            for s in STARTS:
                for e in ENDS:
                    b0, b1 = bill(pr, mix, s), bill(pr, mix, e)
                    savings.append({'model': mid, 'mix': mix_name, 'start': s, 'end': e,
                                    'bill_start': b0, 'bill_end': b1, 'saving': 1 - b1 / b0,
                                    'uncached_over_end': bill(pr, mix, 0) / b1})
    pd.DataFrame(curve).to_csv(OUT / 'cache_curve.csv', index=False)
    sv = pd.DataFrame(savings)
    sv.to_csv(OUT / 'cache_savings.csv', index=False)
    g = session_growth(args.data)
    g.to_csv(OUT / 'cache_session_growth.csv', index=False)

    prim = sv[(sv.model == 'anthropic/claude-sonnet-5.5') & (sv.mix == 'agent') & (sv.start == 0.60) & (sv.end == 0.88)].iloc[0]
    print(f'primary (Sonnet 5.5, agent mix, 0.60 -> 0.88): saving {prim.saving:.1%}, '
          f'${prim.bill_start:.3f} -> ${prim.bill_end:.3f} per million tokens')
    print(sv[sv.mix == 'agent'].pivot_table(index='model', columns=['start', 'end'], values='saving').round(3).to_string())
    print('session growth slopes by app (median over models):')
    print(g.groupby('app').loglog_slope.median().round(2).to_string())


if __name__ == '__main__':
    main()
