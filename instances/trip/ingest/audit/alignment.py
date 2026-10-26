"""Test whether same-length files are positionally aligned (implicit row-order linkage) and whether they are sorted.
Usage: python -I alignment.py <data_root>
"""
import sys, os, glob, itertools, json
import pandas as pd, numpy as np
root = sys.argv[1]
files = sorted(glob.glob(os.path.join(root,'data','**','*.dta'), recursive=True))
dfs = {os.path.relpath(p, root): pd.read_stata(p, convert_categoricals=False) for p in files}
print('ID-like columns (name contains id/emp/person/worker/code/name/team/manager_id/office/dept):')
for k,d in dfs.items():
    hits=[c for c in d.columns if any(s in c.lower() for s in ['id','emp','person','worker','uid','name','team','dept','office','division','location','supervisor','pid'])]
    print('  ',k, hits or 'NONE')
print('\nColumns with unique_ratio==1 (candidate keys):')
for k,d in dfs.items():
    u=[c for c in d.columns if d[c].notna().any() and d[c].nunique()==d[c].notna().sum()]
    print('  ',k, u or 'NONE')
print('\nIs treat column sorted (monotone) within each file?')
for k,d in dfs.items():
    if 'treat' in d:
        t=d.treat.values; print('  ',k, 'sorted:', bool((np.diff(t)>=0).all() or (np.diff(t)<=0).all()), 'n_runs:', int(1+(np.diff(t)!=0).sum()))
print('\nPositional equality of treat across same-length files:')
by_len={}
for k,d in dfs.items():
    if 'treat' in d: by_len.setdefault(len(d),[]).append(k)
for n,ks in by_len.items():
    if len(ks)<2: continue
    print(f' length {n}:')
    for a,b in itertools.combinations(ks,2):
        eq=float((dfs[a].treat.values==dfs[b].treat.values).mean())
        print(f'   {a} vs {b}: treat positional match = {eq:.4f}')
# cross-check other shared columns among 1612-row files
print('\nPositional equality of other shared columns (1612-row files):')
a=dfs['data/extendedtable137_a.dta']; f2=dfs['data/figure2.dta']; b=dfs['data/extendedtable137_b.dta']
print('  managerial(ET137a) vs role(fig2):', float((a.managerial.values==f2.role.values).mean()))
print('  female(ET137a) vs 1-male(fig2):', float((a.female.values==(1-f2.male.values)).mean()))
print('  volunteer(ET137a) vs volunteer(ET137b):', float((a.volunteer.values==b.volunteer.values).mean()))
lf_a = (a.commute_hour>0.75).astype(float).where(a.commute_hour.notna());
m = f2.live_far.notna() & a.commute_hour.notna()
print('  live_far(fig2) vs commute_hour>0.75 (ET137a), both nonnull:', float((f2.live_far[m].values==lf_a[m].values).mean()), 'n', int(m.sum()), '; nonnull pattern match:', float((f2.live_far.notna().values==a.commute_hour.notna().values).mean()))
# 1507-row files
print('\nPositional equality among 1507-row files (performance):')
p=dfs['data/figure3/figure3_2021H2.dta']
for s in 'abcdefgh':
    d=dfs[f'data/extendedtable5/table5_left_{s}.dta']
    print(f'  table5_left_{s} performance vs figure3_2021H2 perf:', float((d.performance.values==p.perf_2021h2.values).mean()), ' treat:', float((d.treat.values==p.treat.values).mean()))
for s in 'abcdefgh':
    d=dfs[f'data/extendedtable5/table5_right_{s}.dta']; d2=dfs[f'data/extendedtable5/table5_left_{s}.dta']
    print(f'  table5_right_{s} treat vs left_{s} treat:', float((d.treat.values==d2.treat.values).mean()))
# Are the 1507-row files a subset of the 1612 in order? test whether treat sequence of 1612 with rows dropped could produce 1507 — check if sorted
print('\nSorted-by-treat check (if files are sorted by treat, positional equality is uninformative):')
for k in ['data/extendedtable137_a.dta','data/figure2.dta','data/figure3/figure3_2021H2.dta','data/extendedtable5/table5_left_a.dta','data/extendedtable2.dta','data/figure4.dta']:
    d=dfs[k]; col='control' if 'control' in d else 'treat'
    print('  ',k, col, 'first 40:', ''.join(str(int(x)) for x in d[col].values[:40]))
