# Buyer seat: language-model launch judgment (protocol, fixed before the held-out run)

Written 2026-10-27, before any held-out cutoff was run with this design.

## Question

Does a language model whose training data ends before the data begins judge which newly listed AI models win a use-case segment better than the rule (each provider's earlier launches)?

## Design (frozen)

- Model: `gpt-4.1-mini-2025-04-14`, temperature 0, seed 7. Training data ends 2024-06-01 (OpenAI model page, checked 2026-10-27); usage data starts 2025-01-01.
- Each week a segment (programming, roleplay, all other use) has new listings, the buyer sees the segment's model shares in the week before the cutoff, how launches in the 39 weeks before the cutoff did in that segment, the models listed since the cutoff, and the new models' providers and list prices. It estimates each new model's settled share.
- The kernel sets how much the week's new models take together from market memory: the median share of the segment on models listed in the previous 8 weeks, over the 26 weeks before the cutoff, divided by the median number of listings in 8 weeks. The buyer's estimates only split that amount. The rule splits it by each provider's earlier launches. Everything else (companies, prices, inertia) is identical.
- Development used the first four protocol cutoffs (2025-07-07 to 2025-09-29) only, through `instances/openrouter/ingest/audit/probe_buyer.py`. Held out: the twelve cutoffs 2025-10-27 to 2026-08-31.

## Development results (four cutoffs, 12 segment-cutoffs)

| Measure | Buyer (language model) | Rule | No change |
|---|---:|---:|---:|
| Distance of final-week model mix from actual (points) | 51.2 | 51.8 | 50.6 |
| Share on models listed after the cutoff (actual 34.0%) | 22.4% | 22.7% | 0% |
| Rank correlation of launch judgment with each new model's actual share | 0.36 | 0.27 | n/a |

## Predictions for the held-out twelve cutoffs

1. Launch ranking: the buyer's rank correlation is higher than the rule's.
2. Model-mix distance: buyer and rule within 2 points of each other; neither clearly beats no change.
3. Company tokens: unchanged (price elasticity is small); company spend error within 1 point of the rule.

If prediction 1 fails, the buyer seat adds no measured accuracy and the rule stays the default seat.

## Cost

About 24 calls per cutoff at about $0.002-0.007 each; the twelve held-out cutoffs about $1.5, plus the alternative scenario at the last four cutoffs. Key: OpenAI project key ending uuMA (iMac credential broker). Cap $20; spent before this run $0.28.

## Held-out result (run 2026-10-27)

Source: the evaluation with the language-model buyer, saved on the iMac at `/Volumes/PsychDynamicsData/workcast_ops/evaluation_llm_buyer.json`; responses in `instances/openrouter/data/llm/buyer.jsonl` (591 calls, $0.72 in total including development).

| Measure | Language-model buyer | Rule with the same market memory | Default simulation (rule, no market memory) | No change |
|---|---:|---:|---:|---:|
| Launch rank correlation, 12 held-out cutoffs (36 segment-cutoffs) | 0.40 | 0.38 | n/a | n/a |
| Buyer higher than rule, held out | 23 of 36 (sign test one-sided p 0.07) | | | |
| Launch rank correlation, all 16 cutoffs (48) | 0.39 | 0.35 | n/a | n/a |
| Final-week model-mix distance, all 16 cutoffs (points) | 51.7 | 52.2 | 53.5 | 54.3 |
| Share on models listed after the cutoff (actual 35.7%) | 20.7% | 20.8% | 8.0% | 0% |
| Company spend error, all 16 cutoffs | 38.2% | 40.3% | 36.3% | 41.6% |

Against the predictions: (1) the buyer ranked launches better than the rule, by a small margin that is not statistically clear; (2) buyer and rule were within 2 points on the model mix, and both were slightly closer than no change; (3) spend error did not stay within 1 point of the rule: the buyer was 2.1 points better than the rule with market memory, and 1.9 points worse than the default simulation without it.

Decision: the default buyer seat stays the rule without market memory, because it gives the lowest company spend error. The language-model buyer stays available as a configuration change (`policies/seats.yaml`); its measured edge is in judging which launches win, not in the spend forecast.
