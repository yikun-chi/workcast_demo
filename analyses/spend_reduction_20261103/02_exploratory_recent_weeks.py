#!/usr/bin/env python3
"""EXPLORATORY, outside plan 01. Reads results_01 CSVs only.

Purpose: the weekly range suggested savings grew through the window, and mapped models thin out early.
         This shows the last 8 weeks and lists the incumbents that clear 50%.
Outputs: results_01_20261103/exploratory_recent_weeks.csv, exploratory_incumbents_50pct.csv
Author : Claude Code for Sumer Vaid, 2026-11-03
"""
from pathlib import Path
import pandas as pd
OUT = Path(__file__).resolve().parent / 'results_01_20261103'
weeks = pd.read_csv(OUT / 'savings_by_week.csv', parse_dates=['week'])
recent = weeks[weeks.week >= weeks.week.max() - pd.Timedelta(weeks=7)]
table = recent.groupby('variant').agg(actual=('actual', 'sum'), cf=('cf', 'sum'), low=('saving', 'min'), high=('saving', 'max'))
table['saving'] = 1 - table.cf / table.actual
table.to_csv(OUT / 'exploratory_recent_weeks.csv')
print(table[['saving', 'low', 'high']].round(3).to_string())
print(weeks[weeks.variant == 'primary'][['week', 'saving']].round(3).tail(26).to_string(index=False))
inc = pd.read_csv(OUT / 'savings_by_incumbent.csv')
big = inc[inc.saving >= 0.5].sort_values('actual', ascending=False)
big.to_csv(OUT / 'exploratory_incumbents_50pct.csv', index=False)
print(big[['model', 'spend_share', 'saving']].round(3).to_string(index=False))
print('mapped-only primary saving', round(1 - inc[inc.mapped].cf.sum() / inc[inc.mapped].actual.sum(), 3))
