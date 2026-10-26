"""Reproduce headline numbers of Bloom, Han & Liang (Nature 2024) from the deposit.
Usage: python -I reproduce.py <data_root> <out_json>
"""
import sys, os, json
import numpy as np, pandas as pd
from scipy import stats
root, out = sys.argv[1], sys.argv[2]
R = lambda rel: pd.read_stata(os.path.join(root, rel), convert_categoricals=False)
res = {}
def tt(df, y, g, lo=0, hi=1):
    a = df.loc[df[g]==lo, y].dropna(); b = df.loc[df[g]==hi, y].dropna()
    t = stats.ttest_ind(a, b, equal_var=True)
    return dict(n_lo=int(len(a)), mean_lo=round(float(a.mean()),4), sd_lo=round(float(a.std(ddof=1)),4),
                n_hi=int(len(b)), mean_hi=round(float(b.mean()),4), sd_hi=round(float(b.std(ddof=1)),4),
                diff_hi_minus_lo=round(float(b.mean()-a.mean()),4), p_pooled_t=round(float(t.pvalue),4))

# --- Sample sizes (extendedtable137_a) ---
a = R('data/extendedtable137_a.dta')
res['sample'] = dict(N=int(len(a)), control=int((a.treat==0).sum()), treatment=int((a.treat==1).sum()),
                     non_managers=int((a.managerial==0).sum()), managers=int((a.managerial==1).sum()),
                     volunteers=int((a.volunteer==1).sum()), female=int((a.female==1).sum()),
                     source='data/extendedtable137_a.dta cols treat, managerial, volunteer, female')
# ET1 descriptives
res['extendedtable1_descriptives'] = {c: {k: (None if pd.isna(v) else round(float(v),4)) for k,v in a[c].describe().items()} for c in ['age','children_ind','commute_hour','female','managerial','grad','tenure_years','treat']}
# ET7 balance
res['extendedtable7_balance'] = {c: tt(a, c, 'treat') for c in ['age','children_ind','commute_hour','female','managerial','grad','tenure_years']}
b = R('data/extendedtable137_b.dta')
res['extendedtable7_balance']['prior_performance'] = tt(b, 'prior_performance', 'treat')
res['prior_performance_dist'] = {str(k): int(v) for k,v in b.prior_performance.value_counts(dropna=False).sort_index().items()}
# ET3 volunteer vs non
res['extendedtable3_volunteer'] = {c: tt(a, c, 'volunteer') for c in ['age','children_ind','commute_hour','female','managerial','grad','tenure_years']}
res['extendedtable3_volunteer']['prior_performance'] = tt(b, 'prior_performance', 'volunteer')

# --- Figure 2 attrition ---
f2 = R('data/figure2.dta')
res['figure2_attrition'] = dict(all=tt(f2,'attrite_perc','treat'),
    non_managers=tt(f2[f2.role==0],'attrite_perc','treat'), managers=tt(f2[f2.role==1],'attrite_perc','treat'),
    male=tt(f2[f2.male==1],'attrite_perc','treat'), female=tt(f2[f2.male==0],'attrite_perc','treat'),
    short_commute=tt(f2[f2.live_far==0],'attrite_perc','treat'), long_commute=tt(f2[f2.live_far==1],'attrite_perc','treat'),
    n_attriters=int((f2.attrite_perc==100).sum()), live_far_missing=int(f2.live_far.isna().sum()))
# --- ET2 satisfaction (control==1 means control) ---
e2 = R('data/extendedtable2.dta')
res['extendedtable2_satisfaction'] = {c: tt(e2, c, 'control', lo=1, hi=0) for c in ['work_life_balance','work_satisfaction','life_satisfaction','recommend_friends','quit_intention']}
res['extendedtable2_satisfaction']['_note'] = 'lo = control (control==1), hi = treatment (control==0); N=%d (%d control, %d treatment)' % (len(e2), (e2.control==1).sum(), (e2.control==0).sum())
# --- Figure 3 performance ---
res['figure3_performance'] = {}
for per in ['2021H2','2022H1','2022H2','2023H1']:
    d = R(f'data/figure3/figure3_{per}.dta'); y = f'perf_{per.lower()}'
    r = tt(d, y, 'treat'); r['grade_dist_by_treat'] = {str(int(t)): {str(int(k)): int(v) for k,v in d.loc[d.treat==t, y].value_counts().sort_index().items()} for t in (0,1)}
    res['figure3_performance'][per] = r
# --- Figure 4 promotion ---
f4 = R('data/figure4.dta')
res['figure4_promotion'] = {c: tt(f4, c, 'treat') for c in ['promo_2021h2','promo_2022h1','promo_2022h2','promo_2023h1']}
# --- Figure 5 beliefs ---
f5 = R('data/figure5.dta'); f5['wave_n'] = (f5.wave=='endline').astype(int)
res['figure5_beliefs'] = dict(baseline_vs_endline=tt(f5,'prod_percent','wave_n'),
    endline_by_role=tt(f5[f5.wave=='endline'],'prod_percent','role',1,2), baseline_by_role=tt(f5[f5.wave=='baseline'],'prod_percent','role',1,2),
    n_baseline=int((f5.wave=='baseline').sum()), n_endline=int((f5.wave=='endline').sum()),
    role_counts_by_wave={w: {str(int(k)): int(v) for k,v in f5.loc[f5.wave==w,'role'].value_counts().items()} for w in ('baseline','endline')})
bu = R('data/beliefupdate.dta'); res['beliefupdate'] = tt(bu, 'change', 'treat'); res['beliefupdate']['n_rows']=int(len(bu)); res['beliefupdate']['n_nonmissing']=int(bu.change.notna().sum())
# --- EF1 lines of code ---
ef1 = R('data/extendedfigure1.dta')
res['extendedfigure1_codelines'] = dict(codelines=tt(ef1,'codelines','treat'), log2_codelines=tt(ef1,'log2_codelines','treat'), log2_codelines_1=tt(ef1,'log2_codelines_1','treat'),
    n_rows=int(len(ef1)), share_zero=round(float((ef1.codelines==0).mean()),4), max=float(ef1.codelines.max()),
    implied_engineers_if_653=round(len(ef1)/653,2), note='no engineer id or date column; cannot verify daily structure or 653 engineers')
# --- EF3 takeup ---
ef3 = R('data/extendedfigure3.dta')
g = ef3.groupby(['treat','volunteer']).takeuprate.agg(['count','mean','max']).round(4)
res['extendedfigure3_takeup'] = dict(by_treat_volunteer={f'treat={int(t)},vol={int(v)}': dict(n=int(r['count']), mean=float(r['mean']), max=float(r['max'])) for (t,v),r in g.iterrows()},
    date_min=str(ef3.date.min().date()), date_max=str(ef3.date.max().date()), n_dates=int(ef3.date.nunique()),
    dates_per_group=int(len(ef3)/4), female_col_nonnull=int(ef3.female.notna().sum()),
    takeup_post_2021_09_13_treat={f'vol={int(v)}': round(float(ef3[(ef3.treat==1)&(ef3.volunteer==v)&(ef3.date>='2021-09-13')&(ef3.date<'2022-01-21')].takeuprate.mean()),4) for v in (0,1)},
    takeup_post_2021_09_13_control={f'vol={int(v)}': round(float(ef3[(ef3.treat==0)&(ef3.volunteer==v)&(ef3.date>='2021-09-13')&(ef3.date<'2022-01-21')].takeuprate.mean()),4) for v in (0,1)})
# --- ET5 (OLS with interaction, replicate row 1 and manager rows) ---
import numpy.linalg as la
def ols(df, y, X):
    Xm = np.column_stack([np.ones(len(df))] + [df[c].values for c in X]); yv = df[y].values
    beta, *_ = la.lstsq(Xm, yv, rcond=None); resid = yv - Xm@beta
    s2 = resid@resid/(len(yv)-Xm.shape[1]); se = np.sqrt(np.diag(s2*la.inv(Xm.T@Xm)))
    return {('const' if i==0 else X[i-1]): dict(b=round(float(beta[i]),4), se=round(float(se[i]),4)) for i in range(len(beta))}
t5a = R('data/extendedtable5/table5_left_a.dta'); t5e = R('data/extendedtable5/table5_left_e.dta').assign(mx=lambda d: d.manager*d.treat)
res['extendedtable5'] = dict(performance_on_treat=ols(t5a,'performance',['treat']), performance_manager_interaction=ols(t5e,'performance',['manager','treat','mx']),
    promotion_on_treat=ols(R('data/extendedtable5/table5_right_a.dta'),'promotion',['treat']))
# --- ET6 ---
res['extendedtable6_2021H2'] = {c: tt(R('data/extendedtable6/Tasks2021H2.dta'), c, 'treat') for c in ['Communication','Development','Efficiency','Execution','Innovation','Leadership','Learning','Project','Risk']}
json.dump(res, open(out,'w'), indent=1)
print(json.dumps(res, indent=1))
