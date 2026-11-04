#!/usr/bin/env python3
"""Plan 02, script 05: tokens on superseded versions and the list-price change of moving them to the newest.

Purpose : the version-lag lever in plan_02_levers_to_half.md, on OpenRouter weekly tokens and prices.
Inputs  : --data <instances/openrouter/data> (normalized/model_weekly, price_weekly, models); families_02.csv
Outputs : results_02_20261103/version_lag.csv, version_lag_by_family.csv
Author  : Claude Code for Sumer Vaid, 2026-11-03
Usage   : python 05_version_lag_lever.py --data /path/to/instances/openrouter/data
"""
import argparse
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / 'results_02_20261103'
WEEKS = pd.date_range('2026-09-28', '2026-10-19', freq='7D')  # Plan 02: the last four complete weeks.


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', required=True, type=Path)
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    fam = pd.read_csv(HERE / 'families_02.csv')
    mw = pd.read_parquet(args.data / 'normalized/model_weekly.parquet')
    pw = pd.read_parquet(args.data / 'normalized/price_weekly.parquet')
    models = pd.read_parquet(args.data / 'normalized/models.parquet').set_index('model')
    w = mw[mw.week.isin(WEEKS)].merge(pw[['week', 'model', 'blended_usd_mtok']], on=['week', 'model'], how='left')
    total_tokens = w.tokens.sum()
    w = w.merge(fam, on='model', how='inner')
    # Newest version by the catalog's creation date, with the date in the slug as a fallback.
    created = models.created.reindex(fam.model)
    fallback = pd.to_datetime(fam.model.str.extract(r'-(\d{8})')[0], format='%Y%m%d', errors='coerce').values
    fam['created'] = created.fillna(pd.Series(fallback, index=fam.model)).values
    newest = fam.sort_values('created').groupby('family').model.last()
    w['newest'] = w.family.map(newest)
    w['lagged'] = w.model != w.newest
    newest_price = w[~w.lagged][['week', 'family', 'blended_usd_mtok']].rename(columns={'blended_usd_mtok': 'newest_price'})
    w = w.merge(newest_price, on=['week', 'family'], how='left')
    w['spend'] = w.tokens * w.blended_usd_mtok
    w['cf_spend'] = w.tokens * w.blended_usd_mtok.where(~w.lagged, w.newest_price)
    ok = w.dropna(subset=['blended_usd_mtok', 'newest_price'])

    by = ok.groupby('family').apply(lambda g: pd.Series({
        'newest': g.newest.iloc[0], 'tokens': g.tokens.sum(),
        'lagged_token_share': g.tokens[g.lagged].sum() / g.tokens.sum(),
        'spend': g.spend.sum(), 'cf_spend': g.cf_spend.sum(),
        'spend_change': g.cf_spend.sum() / g.spend.sum() - 1,
        'lagged_spend_change': (g.cf_spend[g.lagged].sum() / g.spend[g.lagged].sum() - 1) if g.spend[g.lagged].sum() > 0 else float('nan'),
    })).reset_index()
    by.to_csv(OUT / 'version_lag_by_family.csv', index=False)
    summary = pd.DataFrame([{
        'weeks': f'{WEEKS[0].date()} to {WEEKS[-1].date()}',
        'family_tokens_share_of_market': ok.tokens.sum() / total_tokens,
        'lagged_token_share_within_families': ok.tokens[ok.lagged].sum() / ok.tokens.sum(),
        'lagged_spend_share_within_families': ok.spend[ok.lagged].sum() / ok.spend.sum(),
        'spend_change_all_families': ok.cf_spend.sum() / ok.spend.sum() - 1,
        'spend_change_on_lagged_tokens': ok.cf_spend[ok.lagged].sum() / ok.spend[ok.lagged].sum() - 1,
        'spend_change_families_where_newest_is_cheaper': (ok.cf_spend.sum() - ok.spend.sum()) / ok.spend.sum(),
    }])
    cheaper = by[by.lagged_spend_change < 0]
    summary['spend_change_on_lagged_tokens_cheaper_families_only'] = (cheaper.cf_spend.sum() - cheaper.spend.sum()) / (
        ok[ok.family.isin(cheaper.family) & ok.lagged].spend.sum()) if len(cheaper) else float('nan')
    summary.to_csv(OUT / 'version_lag.csv', index=False)
    print(summary.T.to_string())
    print(by.round(3).to_string(index=False))


if __name__ == '__main__':
    main()
