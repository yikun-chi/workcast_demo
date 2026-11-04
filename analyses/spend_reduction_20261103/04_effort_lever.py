#!/usr/bin/env python3
"""Plan 02, script 04: the cheapest reasoning effort whose score sits within noise of a higher effort.

Purpose : the effort lever in plan_02_levers_to_half.md, on Epoch's CursorBench and DeepSWE tables.
Inputs  : --epoch <dir with cursorbench_external.csv, deepswe_external.csv, benchmark_data.zip>
Outputs : results_02_20261103/effort_by_model.csv, effort_summary.csv, effort_inputs_sha256.txt
Author  : Claude Code for Sumer Vaid, 2026-11-03
Usage   : python 04_effort_lever.py --epoch /path/to/inputs_external/epoch
"""
import argparse
import hashlib
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / 'results_02_20261103'
ORDER = ['minimal', 'low', 'medium', 'high', 'xhigh', 'max']
CURSOR_MARGIN = 0.02  # Plan 02: CursorBench publishes no error, so the plan 01 margin applies.


def load(epoch):
    cb = pd.read_csv(epoch / 'cursorbench_external.csv')
    cb = cb.rename(columns={'Score': 'score', 'Cost per task': 'cost'})
    cb['effort'] = cb['Model version'].str.extract(r'_(minimal|low|medium|high|xhigh|max)$')[0]
    cb['name'] = cb['Model version'].str.replace(r'_(minimal|low|medium|high|xhigh|max)$', '', regex=True)
    cb['margin'] = CURSOR_MARGIN
    cb['benchmark'] = 'cursorbench'
    ds = pd.read_csv(epoch / 'deepswe_external.csv')
    ds = ds.rename(columns={'Pass@1': 'score', 'Mean cost (USD)': 'cost', 'Reasoning effort': 'effort',
                            '95% CI half-width': 'margin'})
    ds['name'] = ds['Model version'].str.replace(r'_(minimal|low|medium|high|xhigh|max)$', '', regex=True)
    ds['benchmark'] = 'deepswe'
    cols = ['benchmark', 'name', 'effort', 'score', 'cost', 'margin']
    d = pd.concat([cb[cols], ds[cols]]).dropna(subset=['effort', 'score', 'cost'])
    d = d[d.effort.isin(ORDER)]
    d['rank'] = d.effort.map(ORDER.index)
    return d


def cheapest_within(g, ref_effort):
    """Among efforts at or below ref, the cheapest whose score is at least ref score minus the margin.
    Returns None when the reference effort is missing for this model."""
    ref = g[g.effort == ref_effort]
    if ref.empty:
        return None
    ref = ref.iloc[0]
    margin = ref.margin if pd.notna(ref.margin) else CURSOR_MARGIN
    ok = g[(g['rank'] <= ref['rank']) & (g.score >= ref.score - margin) & (g.cost > 0)]
    best = ok.sort_values('cost').iloc[0]
    return {'ref_effort': ref_effort, 'ref_score': ref.score, 'ref_cost': ref.cost, 'margin': margin,
            'chosen_effort': best.effort, 'chosen_score': best.score, 'chosen_cost': best.cost,
            'cost_ratio': best.cost / ref.cost, 'saving': 1 - best.cost / ref.cost}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--epoch', required=True, type=Path)
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    with open(OUT / 'effort_inputs_sha256.txt', 'w') as f:
        for name in ['benchmark_data.zip', 'cursorbench_external.csv', 'deepswe_external.csv']:
            f.write(f'{hashlib.sha256((args.epoch / name).read_bytes()).hexdigest()}  {name}\n')
    d = load(args.epoch)
    rows = []
    for (bench, name), g in d.groupby(['benchmark', 'name']):
        if g.effort.nunique() < 4:  # Plan 02: four or more effort levels.
            continue
        for ref in ['max', 'xhigh', 'high', 'medium']:
            r = cheapest_within(g, ref)
            if r:
                rows.append({'benchmark': bench, 'model': name, 'levels': g.effort.nunique(), **r})
    by = pd.DataFrame(rows)
    by.to_csv(OUT / 'effort_by_model.csv', index=False)
    summ = by.groupby(['benchmark', 'ref_effort']).saving.agg(['count', 'median', 'min', 'max']).reset_index()
    summ.to_csv(OUT / 'effort_summary.csv', index=False)
    print(summ.round(3).to_string(index=False))
    print(by[by.ref_effort.isin(['max', 'high'])][['benchmark', 'model', 'ref_effort', 'chosen_effort', 'ref_score', 'chosen_score', 'saving']].round(3).to_string(index=False))


if __name__ == '__main__':
    main()
