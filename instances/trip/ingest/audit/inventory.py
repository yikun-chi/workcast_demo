"""Inventory every Stata/xlsx data file in the deposit.
Usage: python -I inventory.py <data_root> <out_json>
"""
import sys, os, json, glob
import pandas as pd
root, out = sys.argv[1], sys.argv[2]
files = sorted(glob.glob(os.path.join(root, '**', '*.dta'), recursive=True))
inv = {}
for p in files:
    rel = os.path.relpath(p, root)
    rdr = pd.io.stata.StataReader(p)
    df = rdr.read(convert_categoricals=False)
    vlabels = rdr.variable_labels()
    try:
        vallabels = rdr.value_labels()
    except Exception:
        vallabels = {}
    lbl_map = {}
    try:
        lbl_map = dict(zip(rdr._varlist, rdr._lbllist))
    except Exception:
        pass
    rec = dict(path=rel, n_rows=int(len(df)), n_cols=int(df.shape[1]), columns=[], data_label=rdr.data_label,
               n_duplicate_rows=int(df.duplicated().sum()))
    for c in df.columns:
        s = df[c]
        col = dict(name=c, dtype=str(s.dtype), label=vlabels.get(c, ''), n_null=int(s.isna().sum()),
                   null_rate=round(float(s.isna().mean()), 4), n_unique=int(s.nunique(dropna=True)),
                   unique_ratio=round(float(s.nunique(dropna=True) / max(1, s.notna().sum())), 4))
        if lbl_map.get(c) and lbl_map[c] in vallabels:
            col['value_labels'] = {str(k): v for k, v in vallabels[lbl_map[c]].items()}
        if s.nunique(dropna=True) <= 15:
            vc = s.value_counts(dropna=False).sort_index()
            col['value_counts'] = {str(k): int(v) for k, v in vc.items()}
        elif pd.api.types.is_numeric_dtype(s):
            d = s.describe()
            col['describe'] = {k: (None if pd.isna(v) else round(float(v), 4)) for k, v in d.items()}
        else:
            col['sample_values'] = [str(x) for x in s.dropna().unique()[:8]]
        rec['columns'].append(col)
    inv[rel] = rec
    print(f"\n### {rel}  rows={rec['n_rows']} cols={rec['n_cols']} dup_rows={rec['n_duplicate_rows']} data_label={rdr.data_label!r}")
    for col in rec['columns']:
        extra = col.get('value_counts') or col.get('describe') or col.get('sample_values')
        print(f"  - {col['name']:<24} {col['dtype']:<8} null={col['null_rate']:<6} nuniq={col['n_unique']:<6} uratio={col['unique_ratio']:<6} label={col['label']!r} vlab={col.get('value_labels','')} :: {extra}")
# xlsx
for p in sorted(glob.glob(os.path.join(root, '**', '*.xlsx'), recursive=True)):
    if 'README' in p or 'tilde' in p: continue
    rel = os.path.relpath(p, root)
    x = pd.read_excel(p)
    inv[rel] = dict(path=rel, n_rows=int(len(x)), n_cols=int(x.shape[1]), columns=[dict(name=c, dtype=str(x[c].dtype)) for c in x.columns])
    print(f"\n### {rel} rows={len(x)}"); print(x.to_string())
json.dump(inv, open(out, 'w'), indent=1, default=str)
