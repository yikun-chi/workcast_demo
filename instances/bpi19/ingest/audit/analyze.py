"""Compute feasibility-gate metrics from normalized BPI19 parquet.
Usage: analyze.py <normalized_dir> <out_json>
"""
import sys, json, os, re
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pyarrow.dataset as ds

nd, out_json = sys.argv[1], sys.argv[2]
R = {}

ev = ds.dataset(os.path.join(nd, 'events.parquet'), format='parquet', partitioning='hive').to_table().to_pandas()
cases = pd.read_parquet(os.path.join(nd, 'cases.parquet'))
ev['ts'] = pd.to_datetime(ev['ts'], utc=True)
ev = ev.sort_values(['case_id', 'ts', '_pos'], kind='stable').reset_index(drop=True)
n_ev = len(ev); n_cases = len(cases)
R['n_events'] = n_ev; R['n_cases'] = n_cases
R['n_case_ids_in_events'] = int(ev['case_id'].nunique())
R['cases_with_zero_events'] = int((cases['n_events'] == 0).sum())
R['duplicate_case_ids'] = int(cases['concept:name'].duplicated().sum())

# ---------- schema / null rates
def nullrate(s):
    return float((s.isna() | (s.astype('string').str.strip() == '')).mean())
R['event_null_rate'] = {c: nullrate(ev[c]) for c in ev.columns if c not in ('month',)}
R['case_null_rate'] = {c: nullrate(cases[c]) for c in cases.columns}

# ---------- C-G1
act = ev['concept:name'].value_counts()
R['n_activities'] = int(act.size)
R['activities'] = {k: int(v) for k, v in act.items()}
user_col = 'org:resource'
u = ev[user_col].fillna('<<MISSING>>')
R['user_null_or_NONE'] = {'missing': int(ev[user_col].isna().sum()), 'NONE': int((ev[user_col] == 'NONE').sum())}
users = u[(u != 'NONE') & (u != '<<MISSING>>')]
distinct_users = users.unique()
is_batch = pd.Series(distinct_users).str.lower().str.startswith('batch')
R['n_distinct_users_total'] = int(len(distinct_users))
R['n_batch_users'] = int(is_batch.sum())
R['n_human_users'] = int((~is_batch).sum())
R['user_name_patterns'] = pd.Series(distinct_users).str.replace(r'\d+', '#', regex=True).value_counts().head(10).to_dict()
R['batch_user_list'] = sorted(pd.Series(distinct_users)[is_batch.values].tolist())
ev['user_class'] = np.where(ev[user_col].isna(), 'missing', np.where(ev[user_col] == 'NONE', 'NONE', np.where(ev[user_col].str.lower().str.startswith('batch'), 'batch', 'human')))
R['events_by_user_class'] = ev['user_class'].value_counts().to_dict()
R['events_by_user_class'] = {k: int(v) for k, v in R['events_by_user_class'].items()}

# ---------- C-G2 per activity
cnw = pd.to_numeric(ev.get('Cumulative net worth (EUR)'), errors='coerce')
ev['cnw'] = cnw
g = ev.groupby('concept:name')
pa_ = pd.DataFrame({
    'n': g.size(),
    'pct_user_none_or_missing': g['user_class'].apply(lambda s: float(s.isin(['NONE', 'missing']).mean())),
    'pct_batch': g['user_class'].apply(lambda s: float((s == 'batch').mean())),
    'pct_human': g['user_class'].apply(lambda s: float((s == 'human').mean())),
    'pct_cnw_nonnull': g['cnw'].apply(lambda s: float(s.notna().mean())),
    'pct_cnw_nonzero': g['cnw'].apply(lambda s: float((s.fillna(0) != 0).mean())),
    'n_distinct_users': g[user_col].nunique(),
}).sort_values('n', ascending=False)
R['per_activity'] = json.loads(pa_.to_json(orient='index'))
R['cnw_overall'] = {'nonnull': float(cnw.notna().mean()), 'nonzero': float((cnw.fillna(0) != 0).mean()), 'describe': cnw.describe().to_dict()}

# ---------- C-G3 purchasing document
pd_col = 'Purchasing Document'
if pd_col in cases.columns:
    per_pd = cases.groupby(pd_col).size()
    R['purchasing_documents'] = {'n_distinct': int(per_pd.size), 'mean_items': float(per_pd.mean()), 'median': float(per_pd.median()), 'p90': float(per_pd.quantile(.9)), 'p99': float(per_pd.quantile(.99)), 'max': int(per_pd.max()), 'share_single_item': float((per_pd == 1).mean())}
    # check case id = PO + item
    cid = cases['concept:name'].astype(str)
    R['case_id_startswith_pd'] = float((cid == cases[pd_col].astype(str) + '_' + cases['Item'].astype(str)).mean())

# ---------- C-G4/5 timestamps
R['ts_min'] = str(ev['ts'].min()); R['ts_max'] = str(ev['ts'].max())
lo, hi = pd.Timestamp('2018-01-01', tz='UTC'), pd.Timestamp('2019-02-01', tz='UTC')
outside = (ev['ts'] < lo) | (ev['ts'] >= hi)
R['events_outside_2018_01_to_2019_01'] = int(outside.sum())
R['events_before_2018'] = int((ev['ts'] < lo).sum()); R['events_after_2019_01'] = int((ev['ts'] >= hi).sum())
R['cases_with_any_event_outside'] = int(ev.loc[outside, 'case_id'].nunique())
R['per_month_events'] = {str(k): int(v) for k, v in ev.groupby(ev['ts'].dt.strftime('%Y-%m')).size().items()}
R['per_year_events'] = {str(k): int(v) for k, v in ev.groupby(ev['ts'].dt.year).size().items()}
# per-month by activity for the odd years
odd = ev[outside]
R['outside_window_activities'] = {k: int(v) for k, v in odd['concept:name'].value_counts().head(15).items()}
R['outside_window_years'] = {str(k): int(v) for k, v in odd['ts'].dt.year.value_counts().sort_index().items()}

cs = ev.groupby('case_id').agg(first=('ts', 'min'), last=('ts', 'max'), n=('ts', 'size'))
cs['dur_days'] = (cs['last'] - cs['first']).dt.total_seconds() / 86400
R['share_cases_first_event_2018'] = float(((cs['first'] >= lo) & (cs['first'] < pd.Timestamp('2019-01-01', tz='UTC'))).mean())
R['cases_first_event_year'] = {str(k): int(v) for k, v in cs['first'].dt.year.value_counts().sort_index().items()}
R['cases_last_event_year'] = {str(k): int(v) for k, v in cs['last'].dt.year.value_counts().sort_index().items()}
reach = ev.groupby('case_id')['concept:name'].agg(lambda s: set(s))
cs['clear_invoice'] = reach.apply(lambda s: 'Clear Invoice' in s)
cs['gr'] = reach.apply(lambda s: 'Record Goods Receipt' in s)
cs['inv'] = reach.apply(lambda s: 'Record Invoice Receipt' in s)
cs['first_act'] = ev.groupby('case_id')['concept:name'].first()
cs['last_act'] = ev.groupby('case_id')['concept:name'].last()
R['share_cases_reach_clear_invoice'] = float(cs['clear_invoice'].mean())
R['share_cases_reach_gr'] = float(cs['gr'].mean())
R['share_cases_reach_invoice_receipt'] = float(cs['inv'].mean())
R['first_activity_dist'] = {k: int(v) for k, v in cs['first_act'].value_counts().head(10).items()}
R['last_activity_dist'] = {k: int(v) for k, v in cs['last_act'].value_counts().head(15).items()}

cases_i = cases.set_index('concept:name')
cs = cs.join(cases_i, how='left')
flag_cols = [c for c in ['Item Category', 'Item Type', 'GR-Based Inv. Verif.', 'Goods Receipt', 'Document Type', 'Spend classification text', 'Company', 'Sub spend area text', 'Spend area text', 'Source'] if c in cases.columns]
R['flag_distributions'] = {c: {str(k): int(v) for k, v in cases[c].value_counts(dropna=False).head(25).items()} for c in flag_cols}
R['n_distinct_case_attr_values'] = {c: int(cases[c].nunique()) for c in cases.columns}
if 'Item Category' in cs.columns:
    fam = cs.groupby('Item Category').agg(n=('n', 'size'), share_clear_invoice=('clear_invoice', 'mean'), share_gr=('gr', 'mean'), share_inv=('inv', 'mean'), median_events=('n', 'median'), median_dur_days=('dur_days', 'median'))
    R['per_item_category'] = json.loads(fam.to_json(orient='index'))
    # combo of flags
    combo = cs.groupby(['Item Category', 'GR-Based Inv. Verif.', 'Goods Receipt']).agg(n=('n', 'size'), share_clear_invoice=('clear_invoice', 'mean'), share_gr=('gr', 'mean')).reset_index()
    R['flag_combos'] = json.loads(combo.to_json(orient='records'))

# ---------- split feasibility
def _ts(x):
    return x if isinstance(x, pd.Timestamp) else pd.Timestamp(x, tz='UTC')
def between(s, a, b):
    return (s >= _ts(a)) & (s < _ts(b))
R['split_cases_created'] = {
    'train_2018-01-01_2018-06-30': int(between(cs['first'], '2018-01-01', '2018-07-01').sum()),
    'val_2018-07-01_2018-08-31': int(between(cs['first'], '2018-07-01', '2018-09-01').sum()),
    'test_2018-09-01_2018-11-30': int(between(cs['first'], '2018-09-01', '2018-12-01').sum()),
    'before_2018': int((cs['first'] < lo).sum()),
    'dec_2018_or_later': int((cs['first'] >= pd.Timestamp('2018-12-01', tz='UTC')).sum()),
}
R['split_events'] = {
    'train': int(between(ev['ts'], '2018-01-01', '2018-07-01').sum()),
    'val': int(between(ev['ts'], '2018-07-01', '2018-09-01').sum()),
    'test': int(between(ev['ts'], '2018-09-01', '2018-12-01').sum()),
}
open_at = {}
for t0 in pd.date_range('2018-09-03', '2018-11-26', freq='7D', tz='UTC'):
    o = ((cs['first'] <= t0) & (cs['last'] > t0))
    open_at[str(t0.date())] = {'open_cases': int(o.sum()), 'open_created_2018': int((o & (cs['first'] >= lo)).sum()), 'open_created_in_test': int((o & (cs['first'] >= pd.Timestamp('2018-09-01', tz='UTC'))).sum()), 'new_cases_next_7d': int(between(cs['first'], t0, t0 + pd.Timedelta(days=7)).sum())}
R['open_cases_at_weekly_t0'] = open_at
m2 = cs[cs['n'] >= 2]
R['case_duration_days_ge2'] = {'n': int(len(m2)), 'median': float(m2['dur_days'].median()), 'p90': float(m2['dur_days'].quantile(.9)), 'p99': float(m2['dur_days'].quantile(.99)), 'max': float(m2['dur_days'].max()), 'mean': float(m2['dur_days'].mean())}
m2_2018 = m2[(m2['first'] >= lo) & (m2['first'] < pd.Timestamp('2019-01-01', tz='UTC'))]
R['case_duration_days_ge2_created2018'] = {'n': int(len(m2_2018)), 'median': float(m2_2018['dur_days'].median()), 'p90': float(m2_2018['dur_days'].quantile(.9)), 'p99': float(m2_2018['dur_days'].quantile(.99))}
R['events_per_case'] = {'mean': float(cs['n'].mean()), 'median': float(cs['n'].median()), 'p90': float(cs['n'].quantile(.9)), 'p99': float(cs['n'].quantile(.99)), 'max': int(cs['n'].max()), 'share_1_event': float((cs['n'] == 1).mean())}
log_end = ev['ts'].max()
R['right_censoring'] = {
    'log_end': str(log_end),
    'share_cases_not_reaching_clear_invoice': float(1 - cs['clear_invoice'].mean()),
    'share_cases_last_event_within_30d_of_log_end': float((cs['last'] >= log_end - pd.Timedelta(days=30)).mean()),
    'share_cases_last_event_within_60d_of_log_end_and_no_clear_invoice': float(((cs['last'] >= log_end - pd.Timedelta(days=60)) & ~cs['clear_invoice']).mean()),
    'share_cases_last_event_after_2018_12_31': float((cs['last'] >= pd.Timestamp('2019-01-01', tz='UTC')).mean()),
    'share_cases_created_2018_not_clear_invoice': float((~cs.loc[cs['first'] >= lo, 'clear_invoice']).mean()) if (cs['first'] >= lo).any() else None,
}

# ---------- process behaviour
seq = ev.groupby('case_id')['concept:name'].agg(lambda s: ' -> '.join(s))
vc = seq.value_counts()
R['n_variants'] = int(vc.size)
R['top_variants'] = [{'variant': k, 'n': int(v), 'share': float(v / n_cases)} for k, v in vc.head(10).items()]
R['share_cases_in_top10_variants'] = float(vc.head(10).sum() / n_cases)
R['share_cases_in_top100_variants'] = float(vc.head(100).sum() / n_cases)
R['share_variants_singleton'] = float((vc == 1).sum() / vc.size)

ev['next_act'] = ev.groupby('case_id')['concept:name'].shift(-1)
ev['next_ts'] = ev.groupby('case_id')['ts'].shift(-1)
ev['next_user'] = ev.groupby('case_id')[user_col].shift(-1)
tr = ev.dropna(subset=['next_act'])
tm = tr.groupby(['concept:name', 'next_act']).size().sort_values(ascending=False)
R['n_transitions'] = int(len(tr))
R['transition_top'] = [{'from': a, 'to': b, 'n': int(n), 'share': float(n / len(tr))} for (a, b), n in tm.head(25).items()]
R['n_distinct_transitions'] = int(tm.size)
# self loops
R['self_loop_share'] = float((tr['concept:name'] == tr['next_act']).mean())

exc = ['Change Quantity', 'Change Price', 'Cancel Invoice Receipt', 'Cancel Goods Receipt', 'Delete Purchase Order Item', 'Remove Payment Block', 'Change Delivery Indicator', 'Change Approval for Purchase Order', 'Change Storage Location', 'Change Currency', 'Change Final Invoice Indicator', 'Change payment term', 'Change Rejection Indicator', 'Reactivate Purchase Order Item', 'Block Purchase Order Item', 'Set Payment Block', 'Cancel Subsequent Invoice', 'Release Purchase Order', 'Update Order Confirmation']
exc_in_log = [a for a in exc if a in act.index] + [a for a in act.index if a.startswith('SRM:') and a not in ('SRM: Created', 'SRM: Complete', 'SRM: Ordered', 'SRM: Awaiting Approval', 'SRM: Document Completed', 'SRM: In Transfer to Execution Syst.', 'SRM: Transfer Failed (E.Sys.)') ]
R['exception_activities_used'] = exc_in_log
is_exc = ev['concept:name'].isin(exc_in_log)
exc_per_case = is_exc.groupby(ev['case_id']).sum().reindex(cs.index).fillna(0)
R['exceptions'] = {'share_cases_ge1': float((exc_per_case >= 1).mean()), 'mean_per_case': float(exc_per_case.mean()), 'p90': float(exc_per_case.quantile(.9)), 'max': int(exc_per_case.max()), 'per_activity_cases': {a: int(ev.loc[ev['concept:name'] == a, 'case_id'].nunique()) for a in exc_in_log}}
# narrower set from the brief
exc_core = [a for a in ['Change Quantity', 'Change Price', 'Cancel Invoice Receipt', 'Cancel Goods Receipt', 'Delete Purchase Order Item', 'Remove Payment Block'] if a in act.index]
e2 = ev['concept:name'].isin(exc_core).groupby(ev['case_id']).sum().reindex(cs.index).fillna(0)
R['exceptions_core6'] = {'activities': exc_core, 'share_cases_ge1': float((e2 >= 1).mean()), 'mean_per_case': float(e2.mean())}

du = ev.groupby('case_id')[user_col].nunique(dropna=True)
R['distinct_users_per_case'] = {'mean': float(du.mean()), 'median': float(du.median()), 'p90': float(du.quantile(.9)), 'max': int(du.max())}
ho = ((tr[user_col] != tr['next_user']) & tr[user_col].notna() & tr['next_user'].notna()).groupby(tr['case_id']).sum().reindex(cs.index).fillna(0)
R['handoffs_per_case'] = {'mean': float(ho.mean()), 'median': float(ho.median()), 'p90': float(ho.quantile(.9)), 'share_cases_ge1': float((ho >= 1).mean())}
hc = ev['user_class']; nhc = ev.groupby('case_id')['user_class'].shift(-1)
hb = pd.crosstab(hc[nhc.notna()], nhc[nhc.notna()])
R['handoff_class_matrix'] = json.loads(hb.to_json(orient='index'))

# ---------- inter-event delays for top transitions
tr = tr.assign(gap_h=(tr['next_ts'] - tr['ts']).dt.total_seconds() / 3600)
delays = []
want = [('Create Purchase Order Item', 'Record Goods Receipt'), ('Record Goods Receipt', 'Record Invoice Receipt'), ('Record Invoice Receipt', 'Clear Invoice'), ('Vendor creates invoice', 'Record Invoice Receipt'), ('Create Purchase Order Item', 'Vendor creates invoice'), ('Record Goods Receipt', 'Record Goods Receipt'), ('Clear Invoice', 'Record Goods Receipt'), ('Record Invoice Receipt', 'Remove Payment Block'), ('Remove Payment Block', 'Clear Invoice')]
top5 = [tuple(x) for x in tm.head(8).index]
for a, b in list(dict.fromkeys(top5 + want)):
    s = tr.loc[(tr['concept:name'] == a) & (tr['next_act'] == b), 'gap_h']
    if len(s) == 0:
        continue
    delays.append({'from': a, 'to': b, 'n': int(len(s)), 'median_h': float(s.median()), 'p90_h': float(s.quantile(.9)), 'mean_h': float(s.mean()), 'share_negative': float((s < 0).mean()), 'share_zero': float((s == 0).mean()), 'share_lt_1min': float((s.abs() < 1 / 60).mean())})
R['transition_delays'] = delays
allgap = tr['gap_h']
R['all_gaps'] = {'share_zero': float((allgap == 0).mean()), 'share_negative': float((allgap < 0).mean()), 'median_h': float(allgap.median()), 'p90_h': float(allgap.quantile(.9))}

# ---------- duplicates / timestamp anomalies
dup_cols = ['case_id', 'concept:name', 'ts', user_col]
R['exact_duplicate_events'] = int(ev.duplicated(subset=[c for c in dup_cols if c in ev.columns] + ['cnw']).sum())
R['events_with_midnight_timestamp'] = int(((ev['ts'].dt.hour == 0) & (ev['ts'].dt.minute == 0) & (ev['ts'].dt.second == 0)).sum())
R['events_midnight_by_activity'] = {k: int(v) for k, v in ev.loc[(ev['ts'].dt.hour == 0) & (ev['ts'].dt.minute == 0) & (ev['ts'].dt.second == 0), 'concept:name'].value_counts().head(10).items()}
R['ts_second_resolution_share'] = float((ev['ts'].dt.microsecond == 0).mean())
R['ts_tz_offsets'] = {str(k): int(v) for k, v in ev['time:timestamp'].astype(str).str[-6:].value_counts().head(5).items()}
R['events_vendor_invoice_before_po'] = None
vi = ev[ev['concept:name'] == 'Vendor creates invoice'].groupby('case_id')['ts'].min()
po = ev[ev['concept:name'] == 'Create Purchase Order Item'].groupby('case_id')['ts'].min()
j = pd.concat([vi.rename('vi'), po.rename('po')], axis=1).dropna()
R['cases_vendor_invoice_before_po_create'] = {'n_both': int(len(j)), 'share_vi_before_po': float((j['vi'] < j['po']).mean())}
# order within trace vs timestamp
ev_sorted_pos = ev.sort_values(['case_id', '_pos'])
R['share_cases_trace_order_equals_ts_order'] = float((ev_sorted_pos.groupby('case_id')['ts'].apply(lambda s: s.is_monotonic_increasing)).mean())

def conv(o):
    if isinstance(o, (np.integer,)): return int(o)
    if isinstance(o, (np.floating,)): return None if np.isnan(o) else float(o)
    if isinstance(o, (pd.Timestamp,)): return str(o)
    return str(o)
json.dump(R, open(out_json, 'w'), indent=2, default=conv)
print('done', n_cases, n_ev)
