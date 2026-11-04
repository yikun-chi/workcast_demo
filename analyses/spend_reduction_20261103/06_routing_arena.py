#!/usr/bin/env python3
"""Plan 02, script 06: how much a per-prompt router saves inside one lab's model pair, and what it costs in losses.

Purpose : the routing lever in plan_02_levers_to_half.md, on LMArena's arena-human-preference-140k.
Inputs  : --arena <dir with train-*.parquet>; --data <instances/openrouter/data> for price_weekly
Outputs : results_02_20261103/routing_pairs.csv, routing_curves.csv, routing_inputs_sha256.txt
Author  : Claude Code for Sumer Vaid, 2026-11-03
Usage   : python 06_routing_arena.py --arena /path/to/inputs_external/arena --data /path/to/instances/openrouter/data
"""
import argparse
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.sparse import hstack, csr_matrix
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold

HERE = Path(__file__).resolve().parent
OUT = HERE / 'results_02_20261103'
# (expensive, cheap, OpenRouter id of expensive, OpenRouter id of cheap). Plan 02 fixes the pairs.
PAIRS = [('claude-opus-4-20250514', 'claude-sonnet-4-20250514', 'anthropic/claude-opus-4', 'anthropic/claude-sonnet-4'),
         ('claude-sonnet-4-20250514', 'claude-3-5-haiku-20241022', 'anthropic/claude-sonnet-4', 'anthropic/claude-3.5-haiku'),
         ('gemini-2.5-pro', 'gemini-2.5-flash', 'google/gemini-2.5-pro', 'google/gemini-2.5-flash'),
         ('o3-2025-04-16', 'o4-mini-2025-04-16', 'openai/o3', 'openai/o4-mini'),
         ('gpt-4.1-2025-04-14', 'gpt-4.1-mini-2025-04-14', 'openai/gpt-4.1', 'openai/gpt-4.1-mini')]
THRESHOLDS = np.round(np.arange(0.50, 0.951, 0.05), 2)
MAX_LOSS = 0.05  # Plan 02: the reported saving is at the most routing with losses on at most 5% of prompts.
SEED = 20261103


def first_user_text(conv):
    for m in conv:
        if m['role'] == 'user':
            parts = m['content']
            return ' '.join(str(p.get('text') or '') for p in parts) if not isinstance(parts, str) else parts
    return ''


def load(arena):
    frames = []
    with open(OUT / 'routing_inputs_sha256.txt', 'w') as f:
        for p in sorted(arena.glob('train-*.parquet')):
            f.write(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n')
            frames.append(pd.read_parquet(p, columns=['model_a', 'model_b', 'winner', 'conversation_a', 'is_code', 'timestamp']))
    d = pd.concat(frames, ignore_index=True)
    d['prompt'] = d.conversation_a.map(first_user_text)
    return d.drop(columns='conversation_a')


def pair_frame(d, exp, cheap):
    m = d[((d.model_a == exp) & (d.model_b == cheap)) | ((d.model_a == cheap) & (d.model_b == exp))].copy()
    m['cheap_lost'] = ((m.winner == 'model_a') & (m.model_a == exp)) | ((m.winner == 'model_b') & (m.model_b == exp))
    m['y'] = ~m.cheap_lost  # cheap does not lose: tie, both_bad, or cheap wins
    return m


def price_ratio(pw, exp_id, cheap_id, start, end):
    w = pw[(pw.week >= start) & (pw.week <= end)]
    e = w[w.model == exp_id].blended_usd_mtok.mean()
    c = w[w.model == cheap_id].blended_usd_mtok.mean()
    return e, c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--arena', required=True, type=Path)
    ap.add_argument('--data', required=True, type=Path)
    ap.add_argument('--min-battles', type=int, default=500, help='plan 02 floor is 500; a lower value is exploratory')
    ap.add_argument('--suffix', default='', help='output file suffix, used for exploratory runs')
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    d = load(args.arena)
    pw = pd.read_parquet(args.data / 'normalized/price_weekly.parquet')
    pairs, curves = [], []
    for exp, cheap, exp_id, cheap_id in PAIRS:
        m = pair_frame(d, exp, cheap)
        n = len(m)
        if n < args.min_battles:  # Plan 02: fewer than 500 battles is uninformative.
            pairs.append({'expensive': exp, 'cheap': cheap, 'battles': n, 'note': f'under {args.min_battles} battles'})
            continue
        oracle = m.y.mean()
        X = TfidfVectorizer(max_features=50000, ngram_range=(1, 2), min_df=2, sublinear_tf=True).fit_transform(m.prompt)
        X = hstack([X, csr_matrix(m.is_code.astype(float).values[:, None])]).tocsr()
        y = m.y.values
        prob = np.zeros(n)
        for tr, te in StratifiedKFold(5, shuffle=True, random_state=SEED).split(X, y):
            clf = LogisticRegression(C=1.0, max_iter=2000).fit(X[tr], y[tr])
            prob[te] = clf.predict_proba(X[te])[:, 1]
        auc = roc_auc_score(y, prob)
        ts = pd.to_datetime(m.timestamp, unit='s', errors='coerce') if np.issubdtype(m.timestamp.dtype, np.number) else pd.to_datetime(m.timestamp)
        e_price, c_price = price_ratio(pw, exp_id, cheap_id, ts.min().floor('D'), ts.max().floor('D'))
        best = None
        for t in THRESHOLDS:
            route = prob >= t
            routed_share = route.mean()
            loss_share = (route & m.cheap_lost.values).mean()
            saving = routed_share * (1 - c_price / e_price) if pd.notna(e_price) and pd.notna(c_price) else float('nan')
            row = {'expensive': exp, 'cheap': cheap, 'threshold': t, 'routed_share': routed_share,
                   'loss_share_of_all_prompts': loss_share, 'saving': saving}
            curves.append(row)
            if loss_share <= MAX_LOSS and (best is None or routed_share > best['routed_share']):
                best = row
        pairs.append({'expensive': exp, 'cheap': cheap, 'battles': n, 'oracle_no_loss_share': oracle,
                      'cheap_loss_share_unrouted': m.cheap_lost.mean(), 'router_auc': auc,
                      'price_expensive': e_price, 'price_cheap': c_price,
                      'oracle_saving': oracle * (1 - c_price / e_price) if pd.notna(e_price) else float('nan'),
                      'threshold_at_5pct_loss': best['threshold'] if best else float('nan'),
                      'routed_share_at_5pct_loss': best['routed_share'] if best else 0.0,
                      'saving_at_5pct_loss': best['saving'] if best else 0.0, 'note': ''})
    pd.DataFrame(pairs).to_csv(OUT / f'routing_pairs{args.suffix}.csv', index=False)
    pd.DataFrame(curves).to_csv(OUT / f'routing_curves{args.suffix}.csv', index=False)
    print(pd.DataFrame(pairs).round(3).to_string(index=False))


if __name__ == '__main__':
    main()
