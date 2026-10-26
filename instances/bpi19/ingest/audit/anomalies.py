"""Drill into duplicates and timestamp anomalies. Usage: anomalies.py <normalized_dir>"""
import sys, os, pandas as pd, pyarrow.dataset as ds
nd = sys.argv[1]
ev = ds.dataset(os.path.join(nd, 'events.parquet'), format='parquet', partitioning='hive').to_table().to_pandas()
ev['ts'] = pd.to_datetime(ev['ts'], utc=True)
ev['cnw'] = pd.to_numeric(ev['Cumulative net worth (EUR)'], errors='coerce')
key = ['case_id', 'concept:name', 'ts', 'org:resource', 'cnw']
d = ev[ev.duplicated(subset=key, keep=False)]
print('dup events (all copies):', len(d), 'extra copies:', int(ev.duplicated(subset=key).sum()), 'cases affected:', d['case_id'].nunique())
print('dup by activity:', d['concept:name'].value_counts().head(8).to_dict())
grp = d.groupby(key).size()
print('copies per dup group:', grp.value_counts().head(6).to_dict())
# same minute but differing cnw?
key2 = ['case_id', 'concept:name', 'ts', 'org:resource']
d2 = ev[ev.duplicated(subset=key2, keep=False)]
print('same case/act/ts/user (ignoring cnw):', len(d2))
print('User == org:resource share:', float((ev['User'] == ev['org:resource']).mean()))
# anomalies
early = ev[ev['ts'] < pd.Timestamp('2017-01-01', tz='UTC')]
print('events before 2017:', len(early), early['concept:name'].value_counts().to_dict())
print(early[['case_id', 'concept:name', 'ts', 'org:resource', 'cnw']].sort_values('ts').head(12).to_string())
late = ev[ev['ts'] >= pd.Timestamp('2019-02-01', tz='UTC')]
print('events >= 2019-02:', len(late)); print(late[['case_id', 'concept:name', 'ts', 'org:resource', 'cnw']].to_string())
# 2019 events by activity and month
e19 = ev[ev['ts'] >= pd.Timestamp('2019-01-01', tz='UTC')]
print('2019+ by month', e19.groupby(e19['ts'].dt.strftime('%Y-%m')).size().to_dict())
print('2019-01 by activity', e19[e19['ts'] < pd.Timestamp('2019-02-01', tz='UTC')]['concept:name'].value_counts().head(8).to_dict())
# minute-resolution check
print('seconds==0 share:', float((ev['ts'].dt.second == 0).mean()))
# item category x item type
cases = pd.read_parquet(os.path.join(nd, 'cases.parquet'))
print(pd.crosstab(cases['Item Category'], cases['Item Type']).to_string())
print(pd.crosstab(cases['Item Category'], [cases['GR-Based Inv. Verif.'], cases['Goods Receipt']]).to_string())
# cases with 1 event: what activity
cs1 = ev.groupby('case_id').size(); one = cs1[cs1 == 1].index
print('1-event cases activity:', ev[ev['case_id'].isin(one)]['concept:name'].value_counts().to_dict())
# Dec 2018 cases and censoring: cases created in test window reaching Clear Invoice
first = ev.groupby('case_id')['ts'].min(); last = ev.groupby('case_id')['ts'].max()
ci = ev[ev['concept:name'] == 'Clear Invoice'].groupby('case_id').size().reindex(first.index).fillna(0) > 0
for lo, hi, name in [('2018-01-01', '2018-07-01', 'train'), ('2018-07-01', '2018-09-01', 'val'), ('2018-09-01', '2018-12-01', 'test'), ('2018-12-01', '2019-01-01', 'dec')]:
    m = (first >= pd.Timestamp(lo, tz='UTC')) & (first < pd.Timestamp(hi, tz='UTC'))
    print(f'{name}: n={int(m.sum())} clear_invoice={float(ci[m].mean()):.3f} median_dur_d={float(((last - first)[m].dt.total_seconds() / 86400).median()):.1f} last_event_after_2019-01-31={float((last[m] >= pd.Timestamp("2019-02-01", tz="UTC")).mean()):.4f} last_in_jan2019={float(((last[m] >= pd.Timestamp("2019-01-01", tz="UTC")) & (last[m] < pd.Timestamp("2019-02-01", tz="UTC"))).mean()):.3f}')
# monthly case creation
print('cases created per month', first.groupby(first.dt.strftime('%Y-%m')).size().to_dict())
# human events per month and active human users per month 2018
h = ev[ev['org:resource'].str.startswith('user_')]
print('active human users per month', h.groupby(h['ts'].dt.strftime('%Y-%m'))['org:resource'].nunique().to_dict())
# user-activity specialization: distinct activities per human user
ua = h.groupby('org:resource')['concept:name'].nunique()
print('activities per human user: median', ua.median(), 'p90', ua.quantile(.9), 'max', ua.max())
ue = h.groupby('org:resource').size()
print('events per human user: median', ue.median(), 'p90', ue.quantile(.9), 'max', ue.max(), 'top5 share', float(ue.sort_values(ascending=False).head(5).sum() / len(h)))
# company split
print('cases per company', cases['Company'].value_counts().to_dict())
