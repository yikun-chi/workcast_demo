"""Human-only user metrics and censoring by item category. Usage: extra_users.py <normalized_dir>"""
import sys, os, json, pandas as pd, pyarrow.dataset as ds
nd = sys.argv[1]
ev = ds.dataset(os.path.join(nd, 'events.parquet'), format='parquet', partitioning='hive').to_table().to_pandas()
ev['ts'] = pd.to_datetime(ev['ts'], utc=True)
ev = ev.sort_values(['case_id', 'ts', '_pos'], kind='stable')
out = {}
h = ev[ev['org:resource'] != 'NONE']
du = h.groupby('case_id')['org:resource'].nunique().reindex(ev['case_id'].unique()).fillna(0)
out['distinct_users_per_case_excl_NONE'] = {'mean': float(du.mean()), 'median': float(du.median()), 'p90': float(du.quantile(.9)), 'max': int(du.max())}
hh = ev[ev['org:resource'].str.startswith('user_')]
du2 = hh.groupby('case_id')['org:resource'].nunique().reindex(ev['case_id'].unique()).fillna(0)
out['distinct_human_users_per_case'] = {'mean': float(du2.mean()), 'median': float(du2.median()), 'p90': float(du2.quantile(.9)), 'max': int(du2.max())}
nxt = h.groupby('case_id')['org:resource'].shift(-1)
ho = ((h['org:resource'] != nxt) & nxt.notna()).groupby(h['case_id']).sum().reindex(ev['case_id'].unique()).fillna(0)
out['handoffs_per_case_excl_NONE'] = {'mean': float(ho.mean()), 'median': float(ho.median()), 'p90': float(ho.quantile(.9)), 'share_ge1': float((ho >= 1).mean())}
# dedup effect
key = ['case_id', 'concept:name', 'ts', 'org:resource', 'Cumulative net worth (EUR)']
out['events_after_exact_dedup'] = int((~ev.duplicated(subset=key)).sum())
# censoring by category for test-window cases
cases = pd.read_parquet(os.path.join(nd, 'cases.parquet')).set_index('concept:name')
first = ev.groupby('case_id')['ts'].min(); last = ev.groupby('case_id')['ts'].max()
ci = (ev[ev['concept:name'] == 'Clear Invoice'].groupby('case_id').size().reindex(first.index).fillna(0) > 0)
df = pd.DataFrame({'first': first, 'last': last, 'ci': ci}).join(cases[['Item Category']])
t = df[(df['first'] >= pd.Timestamp('2018-09-01', tz='UTC')) & (df['first'] < pd.Timestamp('2018-12-01', tz='UTC'))]
out['test_window_by_category'] = json.loads(t.groupby('Item Category').agg(n=('ci', 'size'), share_clear_invoice=('ci', 'mean')).to_json(orient='index'))
tr = df[(df['first'] >= pd.Timestamp('2018-01-01', tz='UTC')) & (df['first'] < pd.Timestamp('2018-07-01', tz='UTC'))]
out['train_window_by_category'] = json.loads(tr.groupby('Item Category').agg(n=('ci', 'size'), share_clear_invoice=('ci', 'mean')).to_json(orient='index'))
# share of 3-way-before-GR train cases that end in Clear Invoice (true completion rate benchmark)
# weekly cutoff: open cases excluding Consignment / deleted
print(json.dumps(out, indent=1))
json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'extra_users.json'), 'w'), indent=1)
