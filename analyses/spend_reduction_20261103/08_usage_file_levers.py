#!/usr/bin/env python3
"""Plan 03, script 08: every quality-neutral lever measured on a real agent workload (Claude Code session logs).

Purpose : implements script 08 of plan_03_real_workload_and_cascade.md. Reads the session logs on this
          laptop, bills every API call at list prices, measures the realized cache rate and the expiry
          re-writes, then applies the levers in the plan's order. Only aggregates are written.
Inputs  : ~/.claude/projects/**/*.jsonl and ~/.claude-harvard/projects/**/*.jsonl (read-only)
          inputs_openrouter/models_2026-11-03.json (list prices, cache read and 5-minute write)
          inputs_03/anthropic_prices_latest_week.csv (fast-mode variants)
Outputs : results_03_20261104/usage_summary.csv, usage_by_month.csv, usage_by_model.csv, levers_file.csv,
          levers_by_month.csv, session_distribution.csv, results_summary_08.md
Author  : Claude Code for Sumer Vaid, 2026-11-04
Usage   : python3 08_usage_file_levers.py [--roots ~/.claude/projects ~/.claude-harvard/projects]
Privacy : no prompt text, path, project name or session id is written; sessions are counted, never named.
"""
import argparse
import csv
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / 'results_03_20261104'

# Log model names -> snapshot ids. "opus" and "fable" are bare aliases written by some client versions;
# they are mapped to the newest member of the family and counted in the summary.
MODEL_MAP = {
    'claude-opus-4-7': 'anthropic/claude-opus-4.7', 'claude-opus-4-8': 'anthropic/claude-opus-4.8',
    'claude-opus-5': 'anthropic/claude-opus-5', 'claude-opus-5-5': 'anthropic/claude-opus-5.5',
    'claude-sonnet-5': 'anthropic/claude-sonnet-5', 'claude-sonnet-5-5': 'anthropic/claude-sonnet-5.5',
    'claude-fable-5': 'anthropic/claude-fable-5', 'claude-fable-5-1': 'anthropic/claude-fable-5.1',
    'claude-fable-5-1[1m]': 'anthropic/claude-fable-5.1', 'claude-haiku-5-5': 'anthropic/claude-haiku-5.5',
    'claude-haiku-4-5': 'anthropic/claude-haiku-4.5', 'claude-haiku-4-5-20251001': 'anthropic/claude-haiku-4.5',
    'claude-sonnet-4-6': 'anthropic/claude-sonnet-4.6',
    'claude-opus-4-6': 'anthropic/claude-opus-4.6',
    'opus': 'anthropic/claude-opus-5.5', 'fable': 'anthropic/claude-fable-5.1', 'sonnet': 'anthropic/claude-sonnet-5.5',
}
# Families in release order; the successor at time t is the newest member listed on OpenRouter by t.
FAMILIES = {
    'opus': ['anthropic/claude-opus-4.6', 'anthropic/claude-opus-4.7', 'anthropic/claude-opus-4.8',
             'anthropic/claude-opus-5', 'anthropic/claude-opus-5.5'],
    'sonnet': ['anthropic/claude-sonnet-4.6', 'anthropic/claude-sonnet-5', 'anthropic/claude-sonnet-5.5'],
    'fable': ['anthropic/claude-fable-5', 'anthropic/claude-fable-5.1'],
    'haiku': ['anthropic/claude-haiku-4.5', 'anthropic/claude-haiku-5.5'],
}
# Fast-mode price lists (iMac price_weekly, week of 2026-11-02): input and output per million. Cache read and
# write keep the standard model's ratios to its input price. Models without a fast list are flagged.
FAST_IDS = {'anthropic/claude-opus-4.7': 'anthropic/claude-4.7-opus-fast-20260512',
            'anthropic/claude-opus-4.8': 'anthropic/claude-4.8-opus-fast-20260528',
            'anthropic/claude-opus-5': 'anthropic/claude-opus-5-fast-20260723'}
LIFETIME_5M, LIFETIME_1H = 300.0, 3600.0
EXPIRY_PREFIX_SHARE = 0.8  # plan 03: a re-write is at least 0.8 of the previous cached prefix


def load_prices():
    snap = json.load(open(HERE / 'inputs_openrouter/models_2026-11-03.json'))['data']
    by_id = {m['id']: m for m in snap}
    created = {m['id']: datetime.fromtimestamp(m.get('created', 0), tz=timezone.utc) for m in snap}
    prices = {}
    for mid, m in by_id.items():
        if not mid.startswith('anthropic/'):
            continue
        p = m['pricing']
        inp = float(p['prompt']) * 1e6
        prices[mid] = {'input': inp, 'output': float(p['completion']) * 1e6,
                       'read': float(p.get('input_cache_read', 0)) * 1e6,
                       'write5': float(p.get('input_cache_write', 0)) * 1e6 or inp * 1.25,
                       'write1h': inp * 2.0}  # Anthropic docs: 1-hour writes at 2x input (sources_02.md)
    fast = {}
    with open(HERE / 'inputs_03/anthropic_prices_latest_week.csv') as fh:
        for row in csv.DictReader(fh):
            fast[row['model']] = (float(row['prompt_usd_mtok']), float(row['completion_usd_mtok']))
    fast_prices = {}
    for std, fid in FAST_IDS.items():
        if fid in fast and std in prices:
            s = prices[std]
            fin, fout = fast[fid]
            ratio = fin / s['input']
            fast_prices[std] = {'input': fin, 'output': fout, 'read': s['read'] * ratio,
                                'write5': s['write5'] * ratio, 'write1h': s['write1h'] * ratio}
    return prices, fast_prices, created


def iter_calls(roots):
    """Yield one row per API call (requestId), with the maximum of each usage field across its records."""
    files = 0
    nbytes = 0
    n_records = 0
    for root in roots:
        for path in sorted(Path(root).expanduser().rglob('*.jsonl')):
            files += 1
            nbytes += path.stat().st_size
            calls = {}
            order = []
            try:
                fh = open(path, 'r', encoding='utf-8', errors='replace')
            except OSError:
                continue
            with fh:
                for line in fh:
                    if '"usage"' not in line or '"assistant"' not in line:
                        continue
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    if r.get('type') != 'assistant':
                        continue
                    m = r.get('message') or {}
                    u = m.get('usage')
                    if not isinstance(u, dict):
                        continue
                    n_records += 1
                    rid = r.get('requestId') or r.get('uuid')
                    cc = u.get('cache_creation') or {}
                    tool_use = any(isinstance(c, dict) and c.get('type') == 'tool_use' for c in (m.get('content') or []))
                    row = {
                        'ts': r.get('timestamp'), 'model': m.get('model') or '', 'speed': u.get('speed') or 'standard',
                        'input': int(u.get('input_tokens') or 0),
                        'creation': int(u.get('cache_creation_input_tokens') or 0),
                        'read': int(u.get('cache_read_input_tokens') or 0),
                        'output': int(u.get('output_tokens') or 0),
                        'thinking': int(((u.get('output_tokens_details') or {}).get('thinking_tokens')) or 0),
                        'c5m': int(cc.get('ephemeral_5m_input_tokens') or 0),
                        'c1h': int(cc.get('ephemeral_1h_input_tokens') or 0),
                        'has_cache_fields': int('cache_read_input_tokens' in u),
                        'tool_use': int(tool_use),
                    }
                    if rid in calls:
                        old = calls[rid]
                        for k in ('input', 'creation', 'read', 'output', 'thinking', 'c5m', 'c1h', 'tool_use', 'has_cache_fields'):
                            old[k] = max(old[k], row[k])
                        if not old['ts'] and row['ts']:
                            old['ts'] = row['ts']
                    else:
                        calls[rid] = row
                        order.append(rid)
            for i, rid in enumerate(order):
                row = calls[rid]
                row['session'] = files  # an integer, never the file name
                row['n_calls_in_session'] = len(order)
                yield row
    return files, nbytes, n_records


def parse_ts(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace('Z', '+00:00'))
    except ValueError:
        return None


def successor_at(mid, t, created):
    for fam, members in FAMILIES.items():
        if mid in members:
            best = mid
            for cand in members[members.index(mid) + 1:]:
                c = created.get(cand)
                if c is not None and t is not None and c <= t:
                    best = cand
            return best
    return mid


def bill_row(r, p, expiry_as_read=False, one_hour=False):
    """Dollars for one call at price set p. Writes: 5-minute at write5, 1-hour at write1h.
    expiry_as_read: the call's expiry re-write tokens are billed as reads.
    one_hour: every write at the 1-hour price, and only re-writes after gaps over one hour stay writes."""
    c5, c1 = r['c5m'], r['c1h']
    if c5 + c1 == 0:
        c5 = r['creation']  # older client versions report creation without the split; treated as 5-minute
    read = r['read']
    if one_hour:
        c5, c1 = 0, c5 + c1
        if r['expiry'] and r['gap'] is not None and r['gap'] <= LIFETIME_1H:
            read += r['expiry_tokens']
            c1 -= r['expiry_tokens']
    elif expiry_as_read and r['expiry']:
        read += r['expiry_tokens']
        if c1 >= r['expiry_tokens']:
            c1 -= r['expiry_tokens']
        else:
            c5 -= r['expiry_tokens'] - c1
            c1 = 0
    c5, c1 = max(c5, 0), max(c1, 0)
    return (r['input'] * p['input'] + read * p['read'] + c5 * p['write5'] + c1 * p['write1h']
            + r['output'] * p['output']) / 1e6


def keepalive_cost(r, p, max_gap=None):
    """Dollars to reach an expiry call with a warm cache. Two strategies, the cheaper is taken:
    5-minute blocks refreshed by a read of the prefix every 5 minutes, or 1-hour blocks refreshed hourly, which
    needs the prefix written at the 1-hour price when the session used 5-minute writes (the premium is charged).
    Each ping is a read of the whole prefix (cache hits refresh the lifetime, Anthropic docs). The call itself then
    pays reads on the former re-write tokens. Returns None when the gap exceeds max_gap (no keep-alive)."""
    g, P = r['gap'], r['prev_prefix']
    if not r['expiry'] or g is None or (max_gap is not None and g > max_gap):
        return None
    import math
    pings5 = max(math.ceil(g / LIFETIME_5M) - 1, 0)
    pings1h = max(math.ceil(g / LIFETIME_1H) - 1, 0)
    premium = 0.0 if r['prev_1h'] else P * (p['write1h'] - p['write5'])
    ping5 = pings5 * P * p['read']
    ping1h = pings1h * P * p['read'] + premium
    return (min(ping5, ping1h) + r['expiry_tokens'] * p['read']) / 1e6


def rewrite_cost(r, p):
    """Dollars the expiry re-write cost at price set p, as billed (1-hour or 5-minute write)."""
    c1 = r['c1h']
    w = p['write1h'] if (c1 >= r['expiry_tokens'] > 0) else p['write5']
    return r['expiry_tokens'] * w / 1e6


def bill_keepalive(r, p, max_gap=None):
    """Bill with the expiry re-write replaced by the cheaper of the re-write itself and a keep-alive."""
    base = bill_row(r, p)
    k = keepalive_cost(r, p, max_gap)
    if k is None:
        return base
    rw = rewrite_cost(r, p)
    return base - rw + min(rw, k)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--roots', nargs='+', default=['~/.claude/projects', '~/.claude-harvard/projects'])
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    prices, fast_prices, created = load_prices()

    gen = iter_calls(args.roots)
    rows = []
    while True:
        try:
            rows.append(next(gen))
        except StopIteration as stop:
            files, nbytes, n_records = stop.value
            break
    df = pd.DataFrame(rows)
    df['t'] = df['ts'].map(parse_ts)
    df = df[df['t'].notna()].copy()
    df['month'] = df['t'].map(lambda t: t.strftime('%Y-%m'))
    df['mid'] = df['model'].map(MODEL_MAP)
    unknown = df[df['mid'].isna()]
    df = df[df['mid'].notna()].copy()
    df['alias'] = df['model'].isin(['opus', 'fable', 'sonnet']).astype(int)
    df['prompt'] = df['input'] + df['creation'] + df['read']

    # Expiry re-writes: within a session, ordered by time.
    df = df.sort_values(['session', 't']).reset_index(drop=True)
    gap, expiry, expiry_tokens, prev_prefix, prev_1h = [], [], [], [], []
    prev = None
    for _, r in df.iterrows():
        if prev is None or prev['session'] != r['session']:
            gap.append(None); expiry.append(0); expiry_tokens.append(0); prev_prefix.append(0); prev_1h.append(0)
        else:
            g = (r['t'] - prev['t']).total_seconds()
            life = LIFETIME_1H if prev['c1h'] > 0 else LIFETIME_5M
            prefix = prev['read'] + prev['creation']
            is_exp = int(g > life and prefix > 0 and r['creation'] >= EXPIRY_PREFIX_SHARE * prefix)
            gap.append(g); expiry.append(is_exp); expiry_tokens.append(r['creation'] if is_exp else 0)
            prev_prefix.append(prefix); prev_1h.append(int(prev['c1h'] > 0))
        prev = r
    df['gap'], df['expiry'], df['expiry_tokens'] = gap, expiry, expiry_tokens
    df['prev_prefix'], df['prev_1h'] = prev_prefix, prev_1h

    # Price sets per call: standard, fast (if the call ran fast and a fast list exists), successor (lever V).
    df['fast'] = (df['speed'] != 'standard').astype(int)
    df['fast_priced'] = (df['fast'] == 1) & df['mid'].isin(fast_prices.keys())
    df['successor'] = [successor_at(m, t, created) for m, t in zip(df['mid'], df['t'])]
    df['lagged'] = (df['successor'] != df['mid']).astype(int)
    df['batchable'] = ((df['n_calls_in_session'] == 1) & (df['tool_use'] == 0)).astype(int)

    def price_for(r, model, use_fast):
        if use_fast and model in fast_prices:
            return fast_prices[model]
        return prices[model]

    recs = []
    for _, r in df.iterrows():
        base = bill_row(r, price_for(r, r['mid'], r['fast_priced']))
        v = bill_row(r, price_for(r, r['successor'], r['fast_priced']))          # lever V
        vf = bill_row(r, price_for(r, r['successor'], False))                    # + lever F
        vfa = bill_row(r, price_for(r, r['successor'], False), expiry_as_read=True)   # + lever A
        vfa1 = bill_row(r, price_for(r, r['successor'], False), one_hour=True)        # A' variant
        vfab = vfa * (0.5 if r['batchable'] else 1.0)                            # + lever B
        vfk = bill_keepalive(r, price_for(r, r['successor'], False))             # V, F, then keep-alive (net of pings)
        vfk8 = bill_keepalive(r, price_for(r, r['successor'], False), max_gap=8 * 3600.0)
        vfkb = vfk * (0.5 if r['batchable'] else 1.0)
        k_alone = bill_keepalive(r, price_for(r, r['mid'], r['fast_priced']))
        k8_alone = bill_keepalive(r, price_for(r, r['mid'], r['fast_priced']), max_gap=8 * 3600.0)
        a_alone = bill_row(r, price_for(r, r['mid'], r['fast_priced']), expiry_as_read=True)
        a1_alone = bill_row(r, price_for(r, r['mid'], r['fast_priced']), one_hour=True)
        f_alone = bill_row(r, price_for(r, r['mid'], False))
        b_alone = base * (0.5 if r['batchable'] else 1.0)
        # Exploratory, quality change: Opus tokens at Sonnet 5.5 prices.
        expl = bill_row(r, prices['anthropic/claude-sonnet-5.5']) if 'opus' in r['mid'] else base
        pr = price_for(r, r['mid'], r['fast_priced'])
        c5, c1 = r['c5m'], r['c1h']
        if c5 + c1 == 0:
            c5 = r['creation']
        recs.append({'base': base, 'v': v, 'vf': vf, 'vfa': vfa, 'vfa1': vfa1, 'vfab': vfab,
                     'vfk': vfk, 'vfk8': vfk8, 'vfkb': vfkb, 'k_alone': k_alone, 'k8_alone': k8_alone,
                     'prompt_per_call': r['prompt'],
                     'a_alone': a_alone, 'a1_alone': a1_alone, 'f_alone': f_alone, 'b_alone': b_alone, 'expl': expl,
                     'cost_read': r['read'] * pr['read'] / 1e6, 'cost_write': (c5 * pr['write5'] + c1 * pr['write1h']) / 1e6,
                     'cost_input': r['input'] * pr['input'] / 1e6, 'cost_output': r['output'] * pr['output'] / 1e6,
                     'cost_expiry': r['expiry_tokens'] * (pr['write1h'] if c1 >= r['expiry_tokens'] > 0 else pr['write5']) / 1e6})
    df = pd.concat([df, pd.DataFrame(recs)], axis=1)

    def levers(d):
        base = d['base'].sum()
        if base == 0:
            return None
        s = lambda col: 1 - d[col].sum() / base
        return {
            'bill_usd': base,
            'cache_rate': d['read'].sum() / max(d['prompt'].sum(), 1),
            'read_share_of_bill': d['cost_read'].sum() / base, 'write_share_of_bill': d['cost_write'].sum() / base,
            'input_share_of_bill': d['cost_input'].sum() / base, 'output_share_of_bill': d['cost_output'].sum() / base,
            'thinking_share_of_output_tokens': d['thinking'].sum() / max(d['output'].sum(), 1),
            'expiry_calls_share': d['expiry'].mean(), 'expiry_write_share_of_bill': d['cost_expiry'].sum() / base,
            'lagged_token_share': (d['lagged'] * d['prompt']).sum() / max(d['prompt'].sum(), 1),
            'fast_call_share': d['fast'].mean(), 'fast_unpriced_calls': int((d['fast'] == 1).sum() - d['fast_priced'].sum()),
            'batchable_bill_share': d.loc[d['batchable'] == 1, 'base'].sum() / base,
            'saving_V_alone': s('v'), 'saving_F_alone': s('f_alone'), 'saving_A_alone': s('a_alone'),
            'saving_A1h_alone': s('a1_alone'), 'saving_B_alone': s('b_alone'),
            'saving_stack_V': s('v'), 'saving_stack_VF': s('vf'), 'saving_stack_VFA': s('vfa'),
            'saving_stack_VFA1h': s('vfa1'), 'saving_stack_VFAB': s('vfab'),
            'saving_K_keepalive_alone': s('k_alone'), 'saving_K8_keepalive_gaps_under_8h_alone': s('k8_alone'),
            'saving_stack_VFK': s('vfk'), 'saving_stack_VFK8': s('vfk8'), 'saving_stack_VFKB': s('vfkb'),
            'mean_prompt_tokens_per_call': d['prompt'].mean(),
            'exploratory_opus_at_sonnet_prices': s('expl'),
            'calls': len(d), 'sessions': d['session'].nunique(),
        }

    overall = levers(df)
    overall.update({'files': files, 'bytes': nbytes, 'assistant_records': n_records, 'api_calls': len(df),
                    'first_call': df['t'].min().strftime('%Y-%m-%d'), 'last_call': df['t'].max().strftime('%Y-%m-%d'),
                    'alias_call_share': df['alias'].mean(), 'unknown_model_calls': len(unknown),
                    'tokens_without_cache_fields_share': (df.loc[df['has_cache_fields'] == 0, 'prompt'].sum()
                                                          / max(df['prompt'].sum(), 1)),
                    'calls_with_1h_writes_share': (df['c1h'] > 0).mean()})
    pd.DataFrame([overall]).T.rename(columns={0: 'value'}).to_csv(OUT / 'usage_summary.csv')

    by_month = []
    for m, d in df.groupby('month'):
        lv = levers(d)
        lv['month'] = m
        by_month.append(lv)
    bm = pd.DataFrame(by_month).set_index('month')
    bm.to_csv(OUT / 'usage_by_month.csv')
    bm[[c for c in bm.columns if c.startswith('saving') or c in ('bill_usd', 'cache_rate', 'sessions')]].to_csv(OUT / 'levers_by_month.csv')

    by_model = df.groupby('mid').agg(calls=('base', 'size'), bill_usd=('base', 'sum'), prompt_tokens=('prompt', 'sum'),
                                     output_tokens=('output', 'sum'), cache_rate=('read', lambda s: s.sum()),
                                     ).reset_index()
    by_model['cache_rate'] = by_model['cache_rate'] / by_model['prompt_tokens'].clip(lower=1)
    by_model['bill_share'] = by_model['bill_usd'] / by_model['bill_usd'].sum()
    by_model.to_csv(OUT / 'usage_by_model.csv', index=False)

    pd.DataFrame([{k: v for k, v in overall.items() if k.startswith('saving') or k in ('bill_usd', 'cache_rate',
                   'expiry_write_share_of_bill', 'batchable_bill_share', 'lagged_token_share', 'fast_call_share')}]
                 ).T.rename(columns={0: 'value'}).to_csv(OUT / 'levers_file.csv')

    unk = unknown.groupby('model').agg(calls=('input', 'size'), prompt_tokens=('read', 'sum')).reset_index() if len(unknown) else pd.DataFrame(columns=['model', 'calls', 'prompt_tokens'])
    unk.to_csv(OUT / 'unknown_models.csv', index=False)
    ex = df[df['expiry'] == 1].copy()
    ex['gap_h'] = ex['gap'] / 3600.0
    ex['bucket'] = pd.cut(ex['gap_h'], [0, 1, 8, 24, 1e9], labels=['under 1h', '1h to 8h', '8h to 24h', 'over 24h'])
    eb = ex.groupby('bucket', observed=True).agg(calls=('base', 'size'), expiry_cost_usd=('cost_expiry', 'sum'),
                                                   median_expiry_tokens=('expiry_tokens', 'median'),
                                                   median_gap_h=('gap_h', 'median')).reset_index()
    eb['expiry_cost_share'] = eb['expiry_cost_usd'] / max(ex['cost_expiry'].sum(), 1e-9)
    eb.to_csv(OUT / 'expiry_gaps.csv', index=False)
    exm = df.groupby('mid').agg(expiry_cost_usd=('cost_expiry', 'sum'), bill_usd=('base', 'sum'),
                                mean_prompt_tokens_per_call=('prompt', 'mean'), calls_1h_writes_share=('c1h', lambda s: (s > 0).mean())).reset_index()
    exm['expiry_share_of_model_bill'] = exm['expiry_cost_usd'] / exm['bill_usd'].clip(lower=1e-9)
    exm.to_csv(OUT / 'expiry_by_model.csv', index=False)
    sess = df.groupby('session').agg(bill=('base', 'sum'), calls=('base', 'size'), prompt=('prompt', 'sum'),
                                     read=('read', 'sum'), stack=('vfab', 'sum'))
    sess['cache_rate'] = sess['read'] / sess['prompt'].clip(lower=1)
    sess['stack_saving'] = 1 - sess['stack'] / sess['bill'].clip(lower=1e-9)
    q = [0.1, 0.25, 0.5, 0.75, 0.9]
    dist = pd.DataFrame({'quantile': q, 'session_bill_usd': sess['bill'].quantile(q).values,
                         'session_calls': sess['calls'].quantile(q).values,
                         'session_cache_rate': sess['cache_rate'].quantile(q).values,
                         'session_stack_saving': sess['stack_saving'].quantile(q).values})
    dist.to_csv(OUT / 'session_distribution.csv', index=False)

    big = bm[bm['sessions'] >= 100]
    lines = ['# Results 08: the real-workload test', '',
             'Generated by `08_usage_file_levers.py`. Every figure is in a CSV in this folder. Aggregates only.', '',
             '- Files read: %d (%.2f GB), assistant records %d, API calls %d, %s to %s' % (
                 files, nbytes / 1e9, n_records, len(df), overall['first_call'], overall['last_call']),
             '- Bill at list prices: $%.2f over %d sessions' % (overall['bill_usd'], overall['sessions']),
             '- Realized cache rate: %.1f%%; reads %.1f%% of the bill, writes %.1f%%, uncached input %.1f%%, output %.1f%%' % (
                 100 * overall['cache_rate'], 100 * overall['read_share_of_bill'], 100 * overall['write_share_of_bill'],
                 100 * overall['input_share_of_bill'], 100 * overall['output_share_of_bill']),
             '- Expiry re-writes: %.1f%% of calls, %.1f%% of the bill' % (100 * overall['expiry_calls_share'], 100 * overall['expiry_write_share_of_bill']),
             '- Lagged tokens %.1f%%; fast-mode calls %.1f%% (%d without a fast price list); batchable sessions %.1f%% of the bill' % (
                 100 * overall['lagged_token_share'], 100 * overall['fast_call_share'], overall['fast_unpriced_calls'], 100 * overall['batchable_bill_share']),
             '- Months with at least 100 sessions: %d of %d' % (len(big), len(bm)),
             '- Tokens without cache fields: %.2f%%; alias model names: %.2f%% of calls; unknown model calls: %d' % (
                 100 * overall['tokens_without_cache_fields_share'], 100 * overall['alias_call_share'], len(unknown)), '',
             '| Lever | Alone | Stacked (V, F, A, B order) |', '|---|---|---|',
             '| V version lag | %.1f%% | %.1f%% |' % (100 * overall['saving_V_alone'], 100 * overall['saving_stack_V']),
             '| F fast mode off | %.1f%% | %.1f%% |' % (100 * overall['saving_F_alone'], 100 * overall['saving_stack_VF']),
             '| A cache lifetime (expiry writes as reads) | %.1f%% | %.1f%% |' % (100 * overall['saving_A_alone'], 100 * overall['saving_stack_VFA']),
             "| A' one-hour lifetime everywhere | %.1f%% | %.1f%% |" % (100 * overall['saving_A1h_alone'], 100 * overall['saving_stack_VFA1h']),
             '| K keep-alive, pings charged, any gap | %.1f%% | %.1f%% |' % (100 * overall['saving_K_keepalive_alone'], 100 * overall['saving_stack_VFK']),
             '| K8 keep-alive, gaps under 8 hours only | %.1f%% | %.1f%% |' % (100 * overall['saving_K8_keepalive_gaps_under_8h_alone'], 100 * overall['saving_stack_VFK8']),
             '| B batch, stacked on K | | %.1f%% |' % (100 * overall['saving_stack_VFKB']),
             '| B batch for headless single-turn sessions | %.1f%% | %.1f%% |' % (100 * overall['saving_B_alone'], 100 * overall['saving_stack_VFAB']),
             '| Exploratory, quality change: Opus at Sonnet prices | %.1f%% | |' % (100 * overall['exploratory_opus_at_sonnet_prices']), '',
             '| Month | Sessions | Bill $ | Cache rate | Stack VFAB (upper bound) | Stack VFKB (pings charged) |', '|---|---|---|---|---|---|']
    for m, r in bm.iterrows():
        lines.append('| %s | %d | %.0f | %.1f%% | %.1f%% | %.1f%% |' % (m, r['sessions'], r['bill_usd'], 100 * r['cache_rate'], 100 * r['saving_stack_VFAB'], 100 * r['saving_stack_VFKB']))
    lines += ['', 'Months at or past 50%% on the upper-bound stack (VFAB): %d of %d; on the keep-alive stack (VFKB): %d of %d' % (
        int((bm['saving_stack_VFAB'] >= 0.5).sum()), len(bm), int((bm['saving_stack_VFKB'] >= 0.5).sum()), len(bm)),
        '', 'Mean prompt tokens per call: %.0f. Calls with 1-hour writes: %.1f%%.' % (overall['mean_prompt_tokens_per_call'], 100 * overall['calls_with_1h_writes_share']),
        '', '| Expiry gap | Calls | Share of expiry cost | Median re-write tokens | Median gap (h) |', '|---|---|---|---|---|']
    for _, r in eb.iterrows():
        lines.append('| %s | %d | %.1f%% | %.0f | %.1f |' % (r['bucket'], r['calls'], 100 * r['expiry_cost_share'], r['median_expiry_tokens'], r['median_gap_h']))
    lines += ['', '| Model | Bill $ | Expiry share of bill | Mean prompt tokens per call | Calls with 1h writes |', '|---|---|---|---|---|']
    for _, r in exm.sort_values('bill_usd', ascending=False).iterrows():
        lines.append('| %s | %.0f | %.1f%% | %.0f | %.1f%% |' % (r['mid'], r['bill_usd'], 100 * r['expiry_share_of_model_bill'], r['mean_prompt_tokens_per_call'], 100 * r['calls_1h_writes_share']))
    (OUT / 'results_summary_08.md').write_text('\n'.join(lines) + '\n')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
