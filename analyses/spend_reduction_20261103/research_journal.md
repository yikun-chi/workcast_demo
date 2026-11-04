# Research journal: spend reduction, 2026-11-03

## Purpose

Test whether public data supports "cut your AI spend by up to 50% without losing productivity". The earlier 48% figure is forecast error on the 100 leading apps. Nobody's spending changed in that test.

## Approach

Plan 01 was committed before any savings number existed (commit ed71bc7). For each week of programming spend on OpenRouter, each model's tokens moved to the cheapest model that scored at least as high on both FrontierCode and WebDev Arena. Token counts stayed fixed. A separate check used observed median session cost in the same tool and turn range.

## Analysis

`01_quality_matched_savings.py` ran on the iMac with read-only data. `02_exploratory_recent_weeks.py` is exploratory and sits outside the plan. No deviations from plan 01. No paid API calls.

## Results

| Measure | Result | Source file |
|---|---|---|
| Primary saving, 26 weeks | 12.9% | savings_summary.csv |
| Weekly range | 0.0% to 33.2% | savings_summary.csv |
| Spend with both scores | 79.5% | results_summary.md |
| Same vendor only | 4.2% | savings_summary.csv |
| US vendors only | 8.5% | savings_summary.csv |
| With a noise margin | 5.7% | savings_summary.csv |
| FrontierCode alone | 22.5% | savings_summary.csv |
| Spend on incumbents saving at least 50% | 5.5% (threshold 25%) | results_summary.md |
| Session check | 12.8%, 209 usable pairs, 58.6% of latest-week spend | session_check.csv |

Verdict under the rationale's table: H-efficient stands, with primary under 15%. The token-illusion check needed no decision at this level, and it landed near the primary number.

Exploratory: the last 8 weeks show 17.5% (weekly 7.8% to 33.2%), and the last four weeks sit near 10%. Counting only models with both scores, the 26-week figure is 16.2%. Five incumbents clear 50%, and together they hold 5.5% of spend. These figures are hypothesis-generating. They replace nothing in the verdict.

Separate lead, read from vendor pages on 2026-11-03: Anthropic (claude.com/pricing), OpenAI (platform.openai.com/docs/guides/batch) and Google (ai.google.dev/gemini-api/docs/batch-api) each publish a 50% batch discount on the same model, for asynchronous work. The share of spend that can wait is unknown from public data.

## What this means

Public data rules out "up to 50%" as a claim about switching models at equal benchmark scores. Productivity stays unmeasured under every branch. Two honest routes remain. One: a 50% batch discount on the same model, limited to work that can wait, which needs a product feature that finds that work. Two: a customer pilot with a before-and-after bill and a productivity measure.

Limits: tokens follow each provider's tokenizer, list prices leave out caching and negotiated deals, benchmarks leave out latency, tool reliability and data residency, and OpenRouter is one marketplace with self-selected, price-aware buyers. Enterprise seat buyers may overpay by more or less, and this test has no data on them.

# Round 02, 2026-11-03: which lever halves the bill

## Purpose

Sumer's instruction after round 01: go all out and find how simulation can cut a company's token bill by half. Round 01 moved one lever, the model, and found 12.9%. This round measures the other four prices in the bill: cache rate, reasoning effort, model version and batch, plus per-prompt routing.

## Approach

Rationale 02 and plan 02 were committed before any lever was computed (commit d405a9a). Inputs: OpenRouter's price snapshot with cache-read, cache-write and batch prices (2026-11-03), OpenRouter's published cache rates and token mix (Inferred 03) and version lag (Inferred 05), Epoch's CursorBench and DeepSWE tables with five effort levels per model, LMArena's 140k per-prompt battles, and the OpenRouter weekly tokens from round 01. A 10,000-company simulation stacks the four quality-neutral levers.

## Analysis

Scripts 03 to 07 ran on the iMac through `run_02.sh`. Deviations are listed in `results_02_20261103/results_summary_02.md`: a Gemini write-price parsing fix in script 03, a wording fix to the routing threshold rule, and an exploratory routing run below the plan's battle floor.

## Results

| Lever | Result | File |
|---|---|---|
| Cache, Sonnet 5.5, agent mix, 0.60 to 0.88 | 57.6% | cache_savings.csv |
| Cache, from 0.44 (January median provider) | 60% to 71% on frontier models | cache_savings.csv |
| Cache, DeepSeek V4.1 Flash | 30.4% | cache_savings.csv |
| Session growth slope, Claude Code and Codex | 1.11 and 1.08 (linear, so cached) | cache_session_growth.csv |
| Effort within noise of max, DeepSWE | median 46.3%, 8 models | effort_summary.csv |
| Effort within noise of max, CursorBench | median 0%, up to 70.4% (Opus 5.5) | effort_summary.csv |
| Version lag, families where newest is cheaper | lagged tokens 15.6% cheaper | version_lag.csv |
| Version lag, all families | spend up 3.9% | version_lag.csv |
| Routing, text-only router | AUC 0.40 to 0.55, under 500 battles per pair | routing_pairs_exploratory_min100.csv |
| Simulation, median company | 41.7% | simulation_summary.csv |
| Simulation, share at or past 50% | 24.3% | simulation_summary.csv |
| Simulation, Opus 5.5 companies at or past 50% | 43.7% | simulation_by_model.csv |

Verdict under rationale 02: H-cache stands, first row of the decision table. The stack lands just under the second row's bar (24.3% against 25%) and so adds to, but does not replace, the cache result. H-route fails.

## What this means

The 50% claim has a public, quality-neutral basis: the same model and the same tokens cost half as much when the cache rate moves from the January 2026 norm to today's agent norm. Cache reads leave outputs byte-identical, so "without losing productivity" holds at the level of outputs for this lever. The site may say "cut your AI bill by up to half on the same models", with the cache rate named as the lever and the January 2026 starting point as the baseline.

What a product has to do to earn the claim: estimate a company's realized cache rate and its causes. The cache lifetime is 5 minutes on Anthropic and 30 minutes on OpenAI, so the gaps between an employee's turns, the stability of the prompt prefix and the minimum cacheable size decide the rate. A world model of the organization that simulates when people send turns predicts the cache rate and the bill under each lifetime, which is a forecast only a simulation of work rhythms can make. The playground's usage upload should report cache reads over prompt tokens from the file when the file has those columns, and otherwise estimate them from turn timing.

Limits. No public dataset gives any one enterprise's cache rate; the starting points are OpenRouter market figures, and a company already at 88% has nothing to gain from this lever. The savings assume the prefix is cacheable at all, which a prompt with a timestamp at the top defeats. DeepSeek-priced models gain under a third. Effort and version levers are model-specific and need the model named. Routing on prompt text alone does not work on arena data. Productivity itself is still unmeasured; the cache lever sidesteps the question by leaving outputs unchanged.

# Round 03, 2026-11-04: the real workload and the verifier cascade

## Purpose

Sumer's instruction on 2026-11-04: reach 50% savings on a customer budget honestly and test everything. Round 02's 50% rested on a market-level cache rate. This round measured every quality-neutral lever on a real five-month agent workload and tested a verifier cascade on public per-instance results, the lever that text-only routing could not deliver.

## Approach

Rationale 03 and plan 03 were committed before any script ran (commit 6090889). Script 08 read 1,722 Claude Code session files on this laptop, billed 72,633 API calls at list prices with cache read and write prices, measured the realized cache rate and the expiry re-writes, and applied version currency, fast mode, cache lifetime (free-cache upper bound and keep-alive with pings charged) and batch. Script 09 took eleven models run through one scaffold on SWE-bench Verified (500 instances, per-instance cost and resolution) and computed, instance by instance, the cost and resolution of cheap-first cascades at verifier accuracies from 0.80 to 1.00.

## Analysis

`run_03.sh` on the laptop, no paid calls. Deviations are listed in `results_03_20261104/results_summary_03.md`: the keep-alive lever added after the first run, one dated model name added to the table, and eleven models in the batch instead of thirteen.

## Results

| Measure | Result | File |
|---|---|---|
| Realized cache rate, real workload | 96.7% | usage_summary.csv |
| Expiry re-writes | 1.3% of calls, 25.0% of the bill | usage_summary.csv |
| Cache lifetime, free warm cache (upper bound) | 23.9% alone, 29.8% stacked | levers_file.csv |
| Cache lifetime, keep-alive with pings charged | 12.0% alone, 19.3% stacked | levers_file.csv |
| Version currency | 5.9% | levers_file.csv |
| Fast mode, batch | 0, 0 | levers_file.csv |
| Months at or past 50% | 0 of 8 (keep-alive), 1 of 8 (upper bound) | usage_by_month.csv |
| Cascade, best pair at 0.90 verifier accuracy | 55.4%, resolve +7.2 pts (MiniMax M2.5 → Claude 4.5 Sonnet) | cascade_summary.csv |
| Cascade against Claude 4.5 Opus, MiniMax first, 0.90 | 53.5%, +3.9 pts | cascade_pairs.csv |
| Cascade, median pair at 0.90 | 9.2% | cascade_summary.csv |
| Best three-model chain at 0.90 | 61.6%, +6.1 pts | cascade_chains.csv |

Verdict under rationale 03: H-already-cached stands and H-stack-real fails; H-cascade stands at verifier accuracy 0.90 and still at 0.80 for the best pair.

## What this means

An honest 50% exists, and it is conditional. The cache rate, round 02's headline, moves nothing for an agent client that already caches at 97%; what remains is 12% to 24% from cache lifetime and 6% from version currency, which a usage file measures in seconds. The 50% comes from a verifier cascade: a cheap model takes every task, the customer's own tests judge the result, and the incumbent model takes the rejects. On SWE-bench Verified that halves the bill with resolution held when the cheap model is close to the incumbent in resolve rate, and it saves 9% when the pair is chosen badly. So the product promise is "measure first": resolve rates for two models on the customer's own test-verified tasks (the Everval frozen-benchmark path), then the cascade number follows from those two rates and the cost ratio, and the cache and version levers add on the same tokens. The site wording that the evidence supports: "for test-verified coding work, half the bill", with the verifier and the measured pair stated, and never a blanket 50%.
