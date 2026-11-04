# Results 03: the real-workload test and the verifier cascade

Run on the laptop on 2026-11-04 with `run_03.sh`. Every number is in a CSV in this folder, named in each table. No paid API calls. Aggregates only; no prompt text, path or session identifier was written.

## Decision

Rationale 03, second row. The quality-neutral stack on the real workload stops at 19.3% with keep-alive pings charged (29.8% as an upper bound with a free warm cache), so H-stack-real fails and H-already-cached stands: a Claude Code workload is 96.7% cached and round 02's cache-rate lever has nothing left to move. The verifier cascade reaches 50% at 90% verifier accuracy with the resolve rate held, so H-cascade stands. The site may say "for test-verified coding work, half the bill", with two conditions named: the customer's tasks have a test that serves as the verifier, and a cheap model resolves nearly as many of those tasks as the incumbent. Both conditions are measured per customer, never assumed.

## Script 08: the real workload (`usage_summary.csv`, `levers_file.csv`, `usage_by_month.csv`, `expiry_gaps.csv`, `expiry_by_model.csv`)

1,722 session files (2.73 GB), 152,809 assistant records, 72,633 API calls from 2026-04-20 to 2026-11-04, 1,639 sessions. Bill at list prices $20,803 (the account pays a subscription; the bill is what these tokens cost on the API). Mean prompt per call 295,581 tokens. 59.4% of calls write 1-hour cache blocks.

| Measure | Value |
|---|---|
| Realized cache rate | 96.7% |
| Bill: cache reads / cache writes / uncached input / output | 48.9% / 39.4% / 0.1% / 11.6% |
| Expiry re-writes (a gap longer than the cache lifetime, then a re-write of the whole prefix) | 1.3% of calls, 25.0% of the bill |
| Tokens on a superseded model version | 12.3% |
| Fast-mode calls; headless single-turn sessions | 0; 0 |

| Lever | Alone | Stacked (V, F, then the cache lever, then B) |
|---|---|---|
| V version currency, same family, successor's prices | 5.9% | 5.9% |
| F fast mode off | 0.0% | 5.9% |
| A free warm cache (expiry writes billed as reads), upper bound | 23.9% | 29.8% |
| A' 1-hour lifetime on every write | -1.6% | 4.2% |
| K keep-alive: cheapest of re-write, 5-minute pings, or 1-hour blocks plus hourly pings | 12.0% | 19.3% |
| K8 keep-alive only across gaps under 8 hours | 10.3% | 16.4% |
| B batch | 0.0% | 19.3% |
| Exploratory, a quality change: Opus tokens at Sonnet 5.5 prices | 31.2% | |

Months at or past 50%: 0 of 8 on the keep-alive stack (best month 42.6%, September), 1 of 8 on the upper bound (55.5%). Expiry cost by gap: under one hour 7.2%, one to eight hours 43.0%, eight to 24 hours 23.1%, over 24 hours 26.7%; the median re-write is 276,000 to 419,000 tokens. Claude Fable 5 carries 41% of the bill and 28.5% of that is expiry re-writes.

What the file says about round 02: the 60% to 88% cache-rate story is a market average that does not describe an agent client, which already caches at 97%. The cache cost that remains is the lifetime, and the honest lever there is 12% net of pings, up to 24% if the pings were free.

## Script 09: the cascade (`cascade_summary.csv`, `cascade_pairs.csv`, `cascade_chains.csv`, `models_used.csv`)

Eleven models, one scaffold (mini-swe-agent 2.0.0), 500 SWE-bench Verified instances each, per-instance cost and resolution from github.com/SWE-bench/experiments. The cheap model attempts every instance; a verifier of accuracy a accepts a resolved attempt with probability a and catches a failed one with probability a; rejected instances go to the expensive model. Expected cost and resolution are exact sums over instances.

| Verifier accuracy | Pairs with no resolve loss | Pairs at or past 50% | Median pair saving | Best pair | Saving | Resolve change |
|---|---|---|---|---|---|---|
| 1.00 | 55 of 55 | 6 | 10.0% | MiniMax M2.5 → Claude 4.5 Sonnet | 59.5% | +8.4 pts |
| 0.95 | 55 of 55 | 4 | 9.6% | same pair | 57.5% | +7.8 pts |
| 0.90 | 53 of 55 | 3 | 9.2% | same pair | 55.4% | +7.2 pts |
| 0.80 | 44 of 55 | 2 | -5.2% | same pair | 51.3% | +5.9 pts |

Against Claude 4.5 Opus (high), the most expensive model per instance, at 0.90: MiniMax M2.5 first saves 53.5% at +3.9 points; Kimi K2.5 first 38.0% at +1.5; GPT-5 mini first 36.1% at -0.1; Gemini 3 Flash first 15.5% at +3.7. Three-model chains at 0.90: 12 of 165 reach 50% with no loss; the best is GPT-5 mini → MiniMax M2.5 → Claude 4.5 Sonnet at 61.6% and +6.1 points.

The saving is pair-specific. The median pair saves 9%. The pairs that halve the bill all start with a cheap model whose own resolve rate is within a few points of the incumbent (MiniMax M2.5 at 75.8% against Opus 4.5's 76.8%, at a tenth of the cost per instance). Resolve differences of a few points are inside sampling noise at 500 instances, so "no resolve loss" means "within noise of equal".

## Limits

One user's workload, with many headless agent swarms. List prices, with no negotiated discount. The keep-alive counterfactual assumes a cache hit refreshes the lifetime (Anthropic docs) and charges every ping as a full prefix read. The cascade uses hidden tests as the verifier, so verifier accuracy is reported as a parameter from 0.80 to 1.00 rather than assumed; the verification run itself (CI time) is unpriced, and the cascade adds latency on escalated tasks. Prices and model quality are from February 2026 and move; a product must re-measure the pair on the customer's own tasks.

## Deviations from plan 03

- The keep-alive lever K (pings charged) was added after the first run of script 08 showed that lever A, as planned, assumes a free warm cache. A is kept and labelled an upper bound.
- `claude-haiku-4-5-20251001` was added to the model table after the first run listed 1,638 of its calls as unknown (0.3% of prompt tokens).
- Two scaffold submissions dated 2026-02-19 and 2026-02-26 (GPT-5.2 Codex, Gemini 3 Pro) were left out; the plan named the 2026-02-17 batch, which has eleven models, not thirteen as the rationale estimated.
