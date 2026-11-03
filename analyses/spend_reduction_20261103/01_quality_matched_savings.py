#!/usr/bin/env python3
"""Plan 01: how much coding spend on OpenRouter could move to a cheaper model at equal benchmark scores?

Purpose : implements plan_01_quality_matched_savings.md exactly. Reads source data read-only.
Inputs  : --data  instances/openrouter/data (category_weekly, price_weekly, raw/session_cost)
          mapping_01.csv and inputs_epoch/*.csv beside this script
Outputs : results_01_20261103/ beside this script
Author  : Claude Code for Sumer Vaid, 2026-11-03
Usage   : python 01_quality_matched_savings.py --data /path/to/instances/openrouter/data
"""
import argparse
import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
WINDOW_START, WINDOW_END = pd.Timestamp('2026-04-27'), pd.Timestamp('2026-10-26')  # Plan: 26 complete weeks.
CATEGORY = 'programming'
OUT = HERE / 'results_01_20261103'


def load_scores():
    """Plan, quality score: a model's score is its maximum across its mapped Epoch versions."""
    mapping = pd.read_csv(HERE / 'mapping_01.csv')
    fc = pd.read_csv(HERE / 'inputs_epoch/frontiercode_external.csv')
    arena = pd.read_csv(HERE / 'inputs_epoch/webdev_arena_external.csv')
    rows = []
    for m in mapping.itertuples():
        fc_vals = fc[fc['Model version'].isin(m.frontiercode_versions.split(';'))]['Main score']
        ar_vals = arena[arena['Model version'].isin(m.arena_versions.split(';'))]['Arena Score']
        # A mapping that finds nothing is a typo, and a typo would silently change the answer.
        assert len(fc_vals) and len(ar_vals), f'mapping found no score for {m.openrouter_model}'
        rows.append({'model': m.openrouter_model, 'vendor': m.vendor, 'country': m.country,
                     'frontiercode': float(fc_vals.max()), 'arena': float(ar_vals.max())})
    return pd.DataFrame(rows).set_index('model')


def passes(inc, cand, variant):
    """The dominance rule from the plan, with each variant's stated change."""
    if variant == 'frontiercode_only':
        return cand.frontiercode >= inc.frontiercode
    fc_margin, ar_margin = (0.02, 25) if variant == 'margin' else (0, 0)
    ok = cand.frontiercode >= inc.frontiercode + fc_margin and cand.arena >= inc.arena + ar_margin
    if variant == 'same_vendor':
        ok = ok and cand.vendor == inc.vendor
    if variant == 'us_vendors':
        ok = ok and cand.country == 'US'
    return ok


def counterfactual(week_rows, scores, variant):
    """Cheapest passing candidate for each incumbent in one week. Unmapped models keep their price."""
    rows = week_rows.copy()
    rows['cf_price'], rows['replacement'] = rows.blended_usd_mtok, rows.model
    pool = rows[rows.model.isin(scores.index) & (rows.blended_usd_mtok > 0)]
    for i, inc_row in rows.iterrows():
        if inc_row.model not in scores.index:
            continue
        inc = scores.loc[inc_row.model]
        best_price, best_model = inc_row.blended_usd_mtok, inc_row.model  # Capped at the incumbent's own price.
        for cand_row in pool.itertuples():
            if cand_row.model != inc_row.model and cand_row.blended_usd_mtok < best_price and passes(inc, scores.loc[cand_row.model], variant):
                best_price, best_model = cand_row.blended_usd_mtok, cand_row.model
        rows.loc[i, ['cf_price', 'replacement']] = [best_price, best_model]
    rows['cf_spend'] = rows.tokens / 1e6 * rows.cf_price
    return rows


def session_check(data_dir, scores, latest):
    """Plan, session check: observed median session cost in the same harness and turn range."""
    records = []
    for name in ('o0.json', 'o500.json'):
        records += json.load(open(data_dir / 'raw/session_cost/2026-10-27' / name))['data']
    sessions = pd.DataFrame(records).drop_duplicates(['app_slug', 'turn_range', 'model_permaslug'])
    sessions = sessions[sessions.model_permaslug.isin(scores.index) & (sessions.median_session_cost_usd > 0)]
    spend = latest.set_index('model').spend
    out = []
    for (app, turns), group in sessions.groupby(['app_slug', 'turn_range']):
        for inc in group.itertuples():
            options = [c for c in group.itertuples() if c.model_permaslug != inc.model_permaslug
                       and c.median_session_cost_usd < inc.median_session_cost_usd
                       and passes(scores.loc[inc.model_permaslug], scores.loc[c.model_permaslug], 'primary')]
            cheapest = min(options, key=lambda c: c.median_session_cost_usd, default=None)
            out.append({'harness': app, 'turn_range': turns, 'incumbent': inc.model_permaslug, 'incumbent_cost': inc.median_session_cost_usd,
                        'candidate': cheapest.model_permaslug if cheapest else inc.model_permaslug,
                        'candidate_cost': cheapest.median_session_cost_usd if cheapest else inc.median_session_cost_usd,
                        'weight': float(spend.get(inc.model_permaslug, 0))})
    table = pd.DataFrame(out)
    table['saving'] = 1 - table.candidate_cost / table.incumbent_cost
    return table


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', required=True, type=Path)
    args = parser.parse_args()
    OUT.mkdir(exist_ok=True)
    scores = load_scores()
    tokens = pd.read_parquet(args.data / 'normalized/category_weekly.parquet')
    prices = pd.read_parquet(args.data / 'normalized/price_weekly.parquet')
    rows = tokens[(tokens.category == CATEGORY) & tokens.week.between(WINDOW_START, WINDOW_END)].merge(prices, on=['week', 'model'], how='inner')
    rows = rows[rows.blended_usd_mtok.notna()].copy()
    rows['spend'] = rows.tokens / 1e6 * rows.blended_usd_mtok
    total = rows.spend.sum()
    coverage = rows[rows.model.isin(scores.index)].spend.sum() / total

    # One pass per variant, each compared with the same actual spend.
    summary, weekly, primary_rows = [], [], None
    for variant in ['primary', 'same_vendor', 'us_vendors', 'margin', 'frontiercode_only']:
        result = pd.concat([counterfactual(g, scores, variant) for _, g in rows.groupby('week')])
        by_week = result.groupby('week').agg(actual=('spend', 'sum'), cf=('cf_spend', 'sum'))
        by_week['saving'] = 1 - by_week.cf / by_week.actual
        weekly.append(by_week.assign(variant=variant).reset_index())
        summary.append({'variant': variant, 'actual_spend_usd': total, 'counterfactual_spend_usd': result.cf_spend.sum(),
                        'saving': 1 - result.cf_spend.sum() / total, 'weekly_min': by_week.saving.min(), 'weekly_max': by_week.saving.max()})
        if variant == 'primary':
            primary_rows = result
    summary = pd.DataFrame(summary)
    summary.to_csv(OUT / 'savings_summary.csv', index=False)
    pd.concat(weekly).to_csv(OUT / 'savings_by_week.csv', index=False)

    # Saving per incumbent, for the words "up to".
    by_inc = primary_rows.groupby('model').agg(actual=('spend', 'sum'), cf=('cf_spend', 'sum'), tokens=('tokens', 'sum')).sort_values('actual', ascending=False)
    by_inc['saving'] = 1 - by_inc.cf / by_inc.actual
    by_inc['spend_share'] = by_inc.actual / total
    by_inc['mapped'] = by_inc.index.isin(scores.index)
    by_inc.to_csv(OUT / 'savings_by_incumbent.csv')
    share_at_50 = by_inc[by_inc.saving >= 0.5].actual.sum() / total

    pairs = primary_rows[primary_rows.model != primary_rows.replacement].groupby(['model', 'replacement']).agg(tokens=('tokens', 'sum'), saved=('spend', 'sum'), cf=('cf_spend', 'sum'))
    pairs['saved_usd'] = pairs.saved - pairs.cf
    pairs.drop(columns=['saved', 'cf']).sort_values('saved_usd', ascending=False).to_csv(OUT / 'replacement_pairs.csv')

    # Session check on the latest window week.
    latest = rows[rows.week == WINDOW_END]
    sessions = session_check(args.data, scores, latest)
    sessions.to_csv(OUT / 'session_check.csv', index=False)
    usable = sessions[sessions.candidate != sessions.incumbent]
    weight = sessions.drop_duplicates('incumbent').weight.sum()
    session_saving = (sessions.saving * sessions.weight).sum() / sessions.weight.sum() if sessions.weight.sum() else float('nan')
    session_cover = weight / latest.spend.sum()

    # Decision table from rationale 01, applied mechanically.
    p = summary.set_index('variant').saving['primary']
    if coverage < 0.5:
        verdict = 'UNINFORMATIVE: coverage under 50%'
    elif p >= 0.5:
        informative = len(usable) >= 5 and session_cover >= 0.3
        verdict = ('H-overpay stands' if informative and session_saving >= 0.5 and share_at_50 >= 0.25
                   else 'H-token-illusion or too little spend at 50%: use the session number, with no 50%')
    elif p >= 0.15:
        verdict = 'H-partial stands: use the measured number'
    else:
        verdict = 'H-efficient stands: no savings number'

    lines = ['# Results 01: quality-matched savings', '', 'Generated by `01_quality_matched_savings.py`. Every figure below is in a CSV in this folder.', '',
             f'- Window spend at list prices: ${total:,.0f}', f'- Spend on models with both scores: {coverage:.1%}',
             f'- Share of spend on incumbents saving at least 50%: {share_at_50:.1%}',
             f'- Session check: {session_saving:.1%} weighted saving, {len(usable)} usable pairs, {session_cover:.1%} of latest-week spend', f'- **Verdict: {verdict}**', '', '| Variant | Saving | Weekly range |', '|---|---|---|']
    lines += [f'| {r.variant} | {r.saving:.1%} | {r.weekly_min:.1%} to {r.weekly_max:.1%} |' for r in summary.itertuples()]
    (OUT / 'results_summary.md').write_text('\n'.join(lines) + '\n')
    print('\n'.join(lines))
    print(by_inc.head(16)[['spend_share', 'saving', 'mapped']].round(3).to_string())
    print(pd.read_csv(OUT / 'replacement_pairs.csv').head(10).to_string())
    print(usable.sort_values('weight', ascending=False).head(12).round(3).to_string())


if __name__ == '__main__':
    main()
