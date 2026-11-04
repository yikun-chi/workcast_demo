#!/usr/bin/env python3
"""Plan 02, script 07: 10,000 simulated companies, four quality-neutral levers, the share that reaches 50%.

Purpose : the stack test in plan_02_levers_to_half.md. Reads the outputs of scripts 03 and 04 and the
          published version-lag cost changes in sources_02.md. No network, no paid calls.
Inputs  : results_02_20261103/cache_prices_used.csv, effort_by_model.csv
Outputs : results_02_20261103/simulation_companies.csv, simulation_summary.csv, simulation_attribution.csv
Author  : Claude Code for Sumer Vaid, 2026-11-03
Usage   : python 07_company_simulation.py
"""
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / 'results_02_20261103'
N = 10000
SEED = 20261103
MIX = {'agent': (0.87, 0.12, 0.01), 'human': (0.50, 0.38, 0.12)}
TARGET_CACHE = {'agent': 0.88, 'human': 0.60}
# Published list-price change of moving a superseded version to the newest (Inferred 05, sources_02.md).
# Families where the newest costs more get no lever, since no company would move for a higher bill.
VERSION_CHANGE = {'anthropic/claude-sonnet-5.5': -0.36, 'anthropic/claude-opus-5.5': -0.33,
                  'openai/gpt-6.1-sol': -0.55, 'google/gemini-3.8-flash': -0.54,
                  'anthropic/claude-fable-5.1': 0.0, 'openai/gpt-6-luna': 0.0, 'deepseek/deepseek-v4.1-flash': 0.0}
# Snapshot model -> Epoch CursorBench name with four or more effort levels; others get no effort lever.
EFFORT_NAME = {'anthropic/claude-sonnet-5.5': 'claude-sonnet-5-5', 'anthropic/claude-opus-5.5': 'claude-opus-5-5',
               'anthropic/claude-fable-5.1': 'claude-fable-5-1', 'deepseek/deepseek-v4.1-flash': 'deepseek-v4.1-flash-1017'}
EFFORT_START = (['max', 'high', 'medium'], [0.25, 0.50, 0.25])


def bill(p, mix, c):
    eligible, novel, out = mix
    prompt = eligible + novel
    reads = min(c, eligible / prompt) * prompt
    return reads * p.cache_read + (prompt - reads) * p.cache_write + out * p.output


def main():
    rng = np.random.default_rng(SEED)
    prices = pd.read_csv(OUT / 'cache_prices_used.csv').set_index('model')
    eff = pd.read_csv(OUT / 'effort_by_model.csv')
    eff = eff[eff.benchmark == 'cursorbench'].set_index(['model', 'ref_effort']).cost_ratio

    models = prices.index.to_list()
    draws = pd.DataFrame({
        'model': rng.choice(models, N),
        'agent_share': rng.uniform(0.3, 0.9, N),
        'cache_agent_start': rng.uniform(0.44, 0.80, N),
        'effort_start': rng.choice(EFFORT_START[0], N, p=EFFORT_START[1]),
        'lag_share': rng.uniform(0, 0.5, N),
        'batch_share': rng.uniform(0, 0.3, N),
    })
    draws['cache_human_start'] = draws.cache_agent_start / 2

    def company_bill(r, levers):
        p = prices.loc[r.model]
        ca = TARGET_CACHE['agent'] if 'cache' in levers else r.cache_agent_start
        ch = TARGET_CACHE['human'] if 'cache' in levers else r.cache_human_start
        agent = bill(p, MIX['agent'], ca)
        human = bill(p, MIX['human'], ch)
        # Effort: the CursorBench task-cost ratio applies to agent work and to the output part of human work.
        if 'effort' in levers and r.model in EFFORT_NAME and (EFFORT_NAME[r.model], r.effort_start) in eff.index:
            ratio = eff[(EFFORT_NAME[r.model], r.effort_start)]
            agent *= ratio
            human -= MIX['human'][2] * p.output * (1 - ratio)
        total = r.agent_share * agent + (1 - r.agent_share) * human
        if 'version' in levers:
            total *= 1 + r.lag_share * VERSION_CHANGE[r.model]
        if 'batch' in levers:
            total *= 1 - 0.5 * r.batch_share
        return total

    all_levers = ['version', 'effort', 'cache', 'batch']
    start = np.array([company_bill(r, []) for r in draws.itertuples()])
    final = np.array([company_bill(r, all_levers) for r in draws.itertuples()])
    draws['bill_start'] = start
    draws['bill_final'] = final
    draws['saving'] = 1 - final / start
    for lever in all_levers:
        only = np.array([company_bill(r, [lever]) for r in draws.itertuples()])
        without = np.array([company_bill(r, [l for l in all_levers if l != lever]) for r in draws.itertuples()])
        draws[f'saving_{lever}_only'] = 1 - only / start
        draws[f'saving_without_{lever}'] = 1 - without / start
    draws.to_csv(OUT / 'simulation_companies.csv', index=False)

    q = draws.saving.quantile([0.1, 0.25, 0.5, 0.75, 0.9])
    summary = pd.DataFrame([{'companies': N, 'p10': q[0.1], 'p25': q[0.25], 'median': q[0.5], 'p75': q[0.75], 'p90': q[0.9],
                             'share_at_or_past_50pct': (draws.saving >= 0.5).mean(),
                             'share_at_or_past_40pct': (draws.saving >= 0.4).mean(),
                             'median_cache_only': draws.saving_cache_only.median(),
                             'share_50_cache_only': (draws.saving_cache_only >= 0.5).mean()}])
    summary.to_csv(OUT / 'simulation_summary.csv', index=False)
    attr = pd.DataFrame([{'lever': l, 'median_saving_alone': draws[f'saving_{l}_only'].median(),
                          'median_saving_without': draws[f'saving_without_{l}'].median(),
                          'share_50_without': (draws[f'saving_without_{l}'] >= 0.5).mean()} for l in all_levers])
    attr.to_csv(OUT / 'simulation_attribution.csv', index=False)
    by_model = draws.groupby('model').saving.agg(['median', lambda s: (s >= 0.5).mean()]).rename(columns={'<lambda_0>': 'share_50'})
    by_model.to_csv(OUT / 'simulation_by_model.csv')
    print(summary.T.round(3).to_string())
    print(attr.round(3).to_string(index=False))
    print(by_model.round(3).to_string())


if __name__ == '__main__':
    main()
