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
