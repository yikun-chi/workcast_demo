"""Derived rates for the gate table. Usage: python -I derived.py <data_root>"""
import sys, os, pandas as pd, numpy as np
root = sys.argv[1]; R = lambda rel: pd.read_stata(os.path.join(root, rel), convert_categoricals=False)
a = R('data/extendedtable137_a.dta'); f2 = R('data/figure2.dta'); e2 = R('data/extendedtable2.dta'); f5 = R('data/figure5.dta'); f4 = R('data/figure4.dta')
N = len(a); surv = int((f2.attrite_perc == 0).sum())
print('N', N, 'attriters', int((f2.attrite_perc==100).sum()), 'survivors', surv)
print('baseline survey rows (figure5 wave=baseline)', int((f5.wave=='baseline').sum()), 'rate vs N', round((f5.wave=='baseline').sum()/N,4))
print('endline survey rows (figure5 wave=endline)', int((f5.wave=='endline').sum()), 'rate vs N', round((f5.wave=='endline').sum()/N,4), 'rate vs survivors', round((f5.wave=='endline').sum()/surv,4))
print('endline satisfaction rows (ET2)', len(e2), 'rate vs N', round(len(e2)/N,4), 'vs survivors', round(len(e2)/surv,4))
bu = R('data/beliefupdate.dta'); print('beliefupdate rows', len(bu), 'nonmissing change (both waves answered)', int(bu.change.notna().sum()), 'rate vs N', round(bu.change.notna().sum()/N,4))
for per in ['2021H2','2022H1','2022H2','2023H1']:
    d = R(f'data/figure3/figure3_{per}.dta'); print(f'perf {per} rows', len(d), 'coverage vs N', round(len(d)/N,4))
for c in ['promo_2021h2','promo_2022h1','promo_2022h2','promo_2023h1']:
    print(c, 'nonmissing', int(f4[c].notna().sum()), 'coverage', round(f4[c].notna().mean(),4))
# manager-level attrition cells (role x male x live_far x treat)
cells = f2.groupby(['treat','role','male','live_far'], dropna=False).attrite_perc.agg(['count','mean']).round(3)
print('\nAttrition cells (treat, role, male, live_far):'); print(cells.to_string())
print('\nET137_a joint cells treat x managerial x female x grad x children (count):')
print(a.groupby(['treat','managerial','female','grad','children_ind']).size().describe().round(2).to_string())
# commute: distribution
print('\ncommute_hour value counts (top 12):'); print(a.commute_hour.value_counts().head(12).to_string())
print('\nage by managerial:'); print(a.groupby('managerial').age.describe().round(2).to_string())
print('\ntenure by managerial:'); print(a.groupby('managerial').tenure_years.describe().round(2).to_string())
# ET137_a vs ET137_b positional link sanity: prior perf by managerial
b = R('data/extendedtable137_b.dta')
print('\nprior_performance (ET137_b) crosstab with managerial (ET137_a) BY POSITION (a/b share row order):')
print(pd.crosstab(a.managerial, b.prior_performance, dropna=False).to_string())
# extendedfigure3 take-up weekly? date spacing
ef3 = R('data/extendedfigure3.dta'); ds = sorted(ef3.date.unique()); gaps = pd.Series(np.diff(ds)).dt.days.value_counts()
print('\nEF3 date gaps (days) value counts:'); print(gaps.to_string())
print('EF3 dates sample:', [str(pd.Timestamp(d).date()) for d in ds[:12]])
