# Results 02: which lever halves the bill

Run on the iMac on 2026-11-03 with `run_02.sh`. Every number below is in a CSV in this folder; the file is named in each table. No paid API calls.

## Decision

Rationale 02's first row applies. The cache lever alone reaches 50% from a documented public starting point, on the same model, with byte-identical outputs. H-cache stands. The quality-neutral stack puts the median simulated company at 41.7% and 24.3% of companies at or past 50%, just under the 25% bar in the second row, so the stack does not stand on its own but adds to the cache lever. Routing (H-route) fails: text-only routers score no better than chance on these pairs. Effort and version lag are real but model-specific.

## Cache lever (`cache_savings.csv`, `cache_curve.csv`, `cache_prices_used.csv`)

Agent token mix 87% cache-eligible prompt, 12% novel prompt, 1% output (OpenRouter, Inferred 03). Cache rate moves from the documented starting point to 0.88, the September 2026 agent norm. Non-read prompt tokens are charged at the cache-write price, which overstates the final bill.

| Model | From 0.44 (January median provider) | From 0.60 (January agent norm) | From 0.70 |
|---|---|---|---|
| Claude Sonnet 5.5 | 68.2% | 57.6% | 46.6% |
| Claude Opus 5.5 | 68.2% | 57.6% | 46.6% |
| Claude Fable 5.1 | 70.6% | 60.4% | 49.4% |
| GPT-6.1 Sol | 68.2% | 57.6% | 46.6% |
| GPT-6 Luna | 63.5% | 52.5% | 41.5% |
| Gemini 3.8 Flash | 60.3% | 49.1% | 38.3% |
| DeepSeek V4.1 Flash | 40.8% | 30.4% | 21.9% |

Primary: Sonnet 5.5, 0.60 to 0.88, $1.149 to $0.487 per million tokens, 57.6%. Fully uncached, the same tokens cost 5.3 times the 0.88 bill (OpenRouter's own example on Sonnet 5 gives 4 times, with writes ignored).

The human mix (50% eligible, 38% novel, 12% output) caps the cache rate at 0.57, so the human rows in `cache_savings.csv` show zero from a 0.60 start; the lever on human chat is small by construction. In the simulation, human work starts at half the agent rate and moves to the cap.

Session check (`cache_session_growth.csv`): median session cost against turns has a log-log slope of 1.11 for Claude Code, 1.08 for Codex, 1.31 for Hermes Agent and 1.47 for Kilo Code. Linear growth (slope 1) is what a cached prefix gives; quadratic (slope 2) is what re-billing the whole context gives. These tools cache.

## Effort lever (`effort_by_model.csv`, `effort_summary.csv`)

Cheapest effort within noise of the reference effort, same model. CursorBench margin 0.02; DeepSWE margin is the published 95% half-width.

| Benchmark | Reference | Models | Median saving | Range |
|---|---|---|---|---|
| CursorBench | max | 12 | 0% | 0% to 70.4% |
| CursorBench | high | 15 | 0% | 0% to 22.9% |
| DeepSWE | max | 8 | 46.3% | 0% to 59.0% |
| DeepSWE | high | 10 | 0% | 0% to 21.6% |

Where the saving exists it is large: Claude Opus 5.5 at high scores 0.560 against 0.578 at max for 70.4% less per task (CursorBench); on DeepSWE, Claude Fable 5 (57.6%), Claude Opus 5 (48.7%), GPT-5.6 Sol (43.9%) and GPT-6 Astra (59.0%) all hold their max score within the interval at a lower effort. For about half the models, max is the only level inside its own noise, so there is nothing to cut. The lever needs the model named.

## Version lag (`version_lag.csv`, `version_lag_by_family.csv`)

Four weeks, 2026-09-28 to 2026-10-19, eleven families covering 45.6% of market tokens. 36.3% of family tokens and 22.3% of family spend sit on a superseded version (OpenRouter's request-based figure: 24%). Moving every lagged token to the newest version at list prices raises family spend 3.9%, because DeepSeek, Tencent, GLM and Gemini Flash priced their newest versions higher. In families where the newest version is cheaper, lagged tokens would cost 15.6% less: Claude Opus 20.0% less, GPT Luna 52.3% less, GPT Sol 10.3% less, Claude Sonnet 4.0% less, MiniMax 50.0% less. This lever depends on the family and on whether outputs stay as long, which the data does not show.

## Routing (`routing_pairs.csv`, `routing_pairs_exploratory_min100.csv`)

Every pair fell under the plan's 500-battle floor (135 to 351 battles), so the planned test is uninformative. The exploratory run at a 100-battle floor: the cheap sibling ties or wins on 48% to 60% of prompts (oracle), but the text-only router's cross-validated AUC is 0.40 to 0.55, chance level, and at a 5% loss budget it routes 2% to 11% of prompts. On Gemini 2.5 Pro versus Flash, the one pair with prices in the window, that is a 3.9% saving against an oracle 41%. Prompt text alone does not tell a router which prompts the cheaper model can take. A product that routes needs a signal the arena data lacks, such as the task type or a first cheap attempt.

## Company simulation (`simulation_summary.csv`, `simulation_attribution.csv`, `simulation_by_model.csv`, `simulation_companies.csv`)

10,000 companies, seed 20261103, draws as in plan 02, four quality-neutral levers in the order version, effort, cache, batch.

| Statistic | Value |
|---|---|
| p10 | 29.6% |
| p25 | 35.0% |
| median | 41.7% |
| p75 | 49.7% |
| p90 | 57.6% |
| share at or past 50% | 24.3% |
| share at or past 40% | 56.8% |

Attribution (median saving with the lever alone, and with every lever except that one): cache 29.5% alone, 17.4% without; batch 7.4% alone, 37.0% without; version 2.8% alone, 37.5% without; effort 0% alone (a median over models where half have nothing to cut), 39.9% without. Cache is the lever the result depends on. By model, the share of companies at or past 50%: Opus 5.5 43.7%, GPT-6.1 Sol 38.6%, Fable 5.1 30.2%, Sonnet 5.5 24.2%, Gemini 3.8 Flash 23.1%, GPT-6 Luna 8.3%, DeepSeek V4.1 Flash 0.7%. The claim holds for frontier-priced models, where cache reads are 5% of input, and fails for models already priced near the floor.

## Deviations from plan 02

- Script 03 first charged Gemini's listed `input_cache_write` (a storage rate per hour) as the write price, which gave a negative saving. The fix floors the write price at the input price. The committed results use the fixed script; the first run's Gemini row was wrong and nothing else changed.
- Plan 02 wrote "the largest t with a loss share at or under 5%" for the routing threshold; the script takes the threshold with the most routing under that loss budget, which is what the sentence meant. The rule was fixed before any routing number was read.
- The exploratory routing run at a 100-battle floor is outside the plan and labelled as such in its file names.
