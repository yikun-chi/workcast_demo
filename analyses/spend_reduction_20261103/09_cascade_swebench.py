#!/usr/bin/env python3
"""Plan 03, script 09: a verifier cascade on SWE-bench Verified, computed instance by instance.

Purpose : implements script 09 of plan_03_real_workload_and_cascade.md. For every ordered pair of models run
          through one scaffold (mini-swe-agent 2.0.0, SWE-bench/experiments batch of 2026-02-17), the cheap
          model attempts each instance first and the expensive model takes the instances a verifier rejects.
Inputs  : inputs_03/swebench/<submission>/{metadata.yaml, per_instance_details.json}
Outputs : results_03_20261104/cascade_pairs.csv, cascade_chains.csv, cascade_summary.csv, models_used.csv,
          results_summary_09.md
Author  : Claude Code for Sumer Vaid, 2026-11-04
Usage   : python3 09_cascade_swebench.py
"""
import itertools
import json
from pathlib import Path

import pandas as pd
import yaml

HERE = Path(__file__).resolve().parent
IN = HERE / 'inputs_03/swebench'
OUT = HERE / 'results_03_20261104'
ACCURACIES = [1.0, 0.95, 0.90, 0.80]
MIN_INSTANCES = 500


def load():
    models = {}
    for d in sorted(IN.iterdir()):
        if not (d / 'per_instance_details.json').exists():
            continue
        meta = yaml.safe_load(open(d / 'metadata.yaml'))
        det = json.load(open(d / 'per_instance_details.json'))
        rows = pd.DataFrame([{'instance': k, 'cost': float(v.get('cost') or 0), 'resolved': bool(v.get('resolved'))}
                             for k, v in det.items()]).set_index('instance')
        name = d.name.replace('20260217_mini-v2.0.0_', '')
        models[name] = {'rows': rows, 'name': meta['info']['name'], 'resolved_pct': meta['info']['resolved'],
                        'instance_cost': meta['info'].get('instance_cost')}
    return models


def cascade(stages, a):
    """stages: list of per-instance frames (cheapest first). a: verifier accuracy, applied to accepts and rejects.
    Returns expected cost and expected resolved rate, computed exactly from the per-instance outcomes.
    At a stage, a resolved attempt is accepted with probability a (else the chain continues); a failed attempt
    is caught with probability a (else accepted and counted as unresolved). The last stage is always accepted."""
    idx = stages[0].index
    for s in stages[1:]:
        idx = idx.intersection(s.index)
    cost = pd.Series(0.0, index=idx)
    resolved = pd.Series(0.0, index=idx)
    p_continue = pd.Series(1.0, index=idx)
    for k, s in enumerate(stages):
        s = s.loc[idx]
        cost += p_continue * s['cost']
        r = s['resolved'].astype(float)
        if k == len(stages) - 1:
            resolved += p_continue * r
            p_continue = p_continue * 0.0
        else:
            accept_right = a * r                 # resolved and accepted
            accept_wrong = (1 - a) * (1 - r)     # failed and missed by the verifier
            resolved += p_continue * accept_right
            p_continue = p_continue * (1 - accept_right - accept_wrong)
    return cost.sum(), resolved.mean(), len(idx)


def main():
    OUT.mkdir(exist_ok=True)
    models = load()
    used = {k: v for k, v in models.items() if len(v['rows']) >= MIN_INSTANCES}
    pd.DataFrame([{'model': k, 'name': v['name'], 'instances': len(v['rows']), 'resolved_pct_published': v['resolved_pct'],
                   'resolved_pct_file': 100 * v['rows']['resolved'].mean(), 'mean_cost': v['rows']['cost'].mean()}
                  for k, v in used.items()]).sort_values('mean_cost').to_csv(OUT / 'models_used.csv', index=False)

    pairs = []
    for c, e in itertools.permutations(used.keys(), 2):
        rc, re_ = used[c]['rows'], used[e]['rows']
        if rc['cost'].mean() >= re_['cost'].mean():
            continue
        common = rc.index.intersection(re_.index)
        e_cost = re_.loc[common, 'cost'].sum()
        e_res = re_.loc[common, 'resolved'].mean()
        row = {'cheap': c, 'expensive': e, 'instances': len(common), 'cheap_resolve': rc.loc[common, 'resolved'].mean(),
               'expensive_resolve': e_res, 'cheap_mean_cost': rc.loc[common, 'cost'].mean(),
               'expensive_mean_cost': re_.loc[common, 'cost'].mean()}
        for a in ACCURACIES:
            cost, res, _ = cascade([rc, re_], a)
            row['saving_a%d' % round(a * 100)] = 1 - cost / e_cost
            row['resolve_change_a%d' % round(a * 100)] = res - e_res
        pairs.append(row)
    pairs = pd.DataFrame(pairs)
    pairs.to_csv(OUT / 'cascade_pairs.csv', index=False)

    chains = []
    for c, m, e in itertools.permutations(used.keys(), 3):
        rc, rm, re_ = used[c]['rows'], used[m]['rows'], used[e]['rows']
        if not (rc['cost'].mean() < rm['cost'].mean() < re_['cost'].mean()):
            continue
        common = rc.index.intersection(rm.index).intersection(re_.index)
        e_cost = re_.loc[common, 'cost'].sum()
        e_res = re_.loc[common, 'resolved'].mean()
        row = {'cheap': c, 'mid': m, 'expensive': e, 'instances': len(common), 'expensive_resolve': e_res}
        for a in ACCURACIES:
            cost, res, _ = cascade([rc, rm, re_], a)
            row['saving_a%d' % round(a * 100)] = 1 - cost / e_cost
            row['resolve_change_a%d' % round(a * 100)] = res - e_res
        chains.append(row)
    chains = pd.DataFrame(chains)
    chains.to_csv(OUT / 'cascade_chains.csv', index=False)

    summary = []
    for a in ACCURACIES:
        sa, ra = 'saving_a%d' % round(a * 100), 'resolve_change_a%d' % round(a * 100)
        ok = pairs[pairs[ra] >= 0]
        okc = chains[chains[ra] >= 0]
        best = ok.sort_values(sa, ascending=False).head(1)
        bestc = okc.sort_values(sa, ascending=False).head(1)
        summary.append({'verifier_accuracy': a, 'pairs_total': len(pairs), 'pairs_no_resolve_loss': len(ok),
                        'pairs_saving_50_no_loss': int((ok[sa] >= 0.5).sum()),
                        'median_saving_no_loss': ok[sa].median(),
                        'best_pair': '%s -> %s' % (best['cheap'].iloc[0], best['expensive'].iloc[0]) if len(best) else '',
                        'best_pair_saving': best[sa].iloc[0] if len(best) else None,
                        'best_pair_resolve_change': best[ra].iloc[0] if len(best) else None,
                        'chains_saving_50_no_loss': int((okc[sa] >= 0.5).sum()),
                        'best_chain': '%s -> %s -> %s' % (bestc['cheap'].iloc[0], bestc['mid'].iloc[0], bestc['expensive'].iloc[0]) if len(bestc) else '',
                        'best_chain_saving': bestc[sa].iloc[0] if len(bestc) else None,
                        'best_chain_resolve_change': bestc[ra].iloc[0] if len(bestc) else None})
    summary = pd.DataFrame(summary)
    summary.to_csv(OUT / 'cascade_summary.csv', index=False)

    # Pairs against the most expensive frontier member, the buyer's usual incumbent.
    top = pairs.sort_values('expensive_mean_cost', ascending=False)['expensive'].iloc[0]
    vs_top = pairs[pairs['expensive'] == top].sort_values('saving_a90', ascending=False)

    lines = ['# Results 09: the verifier cascade on SWE-bench Verified', '',
             'Generated by `09_cascade_swebench.py`. %d models with %d instances each, one scaffold. Every figure is in a CSV here.' % (
                 len(used), MIN_INSTANCES), '',
             '| Verifier accuracy | Pairs with no resolve loss | Of which saving >= 50% | Median saving (no loss) | Best pair | Saving | Resolve change |',
             '|---|---|---|---|---|---|---|']
    for _, r in summary.iterrows():
        lines.append('| %.2f | %d of %d | %d | %.1f%% | %s | %.1f%% | %+.1f pts |' % (
            r['verifier_accuracy'], r['pairs_no_resolve_loss'], r['pairs_total'], r['pairs_saving_50_no_loss'],
            100 * r['median_saving_no_loss'], r['best_pair'], 100 * (r['best_pair_saving'] or 0), 100 * (r['best_pair_resolve_change'] or 0)))
    lines += ['', 'Against %s (the most expensive model per instance), at verifier accuracy 0.90:' % top, '',
              '| Cheap first | Cheap resolve | Saving | Resolve change |', '|---|---|---|---|']
    for _, r in vs_top.iterrows():
        lines.append('| %s | %.1f%% | %.1f%% | %+.1f pts |' % (r['cheap'], 100 * r['cheap_resolve'], 100 * r['saving_a90'], 100 * r['resolve_change_a90']))
    lines += ['', 'Three-model chains at 0.90: %d of %d reach 50%% with no resolve loss; best %s at %.1f%% (%+.1f pts).' % (
        summary.loc[summary['verifier_accuracy'] == 0.90, 'chains_saving_50_no_loss'].iloc[0], len(chains),
        summary.loc[summary['verifier_accuracy'] == 0.90, 'best_chain'].iloc[0],
        100 * summary.loc[summary['verifier_accuracy'] == 0.90, 'best_chain_saving'].iloc[0],
        100 * summary.loc[summary['verifier_accuracy'] == 0.90, 'best_chain_resolve_change'].iloc[0])]
    (OUT / 'results_summary_09.md').write_text('\n'.join(lines) + '\n')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
