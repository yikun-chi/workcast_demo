# Plan 02: five levers and a company simulation

Written 2026-11-03 before any script in this plan ran. Scripts 03 to 07 implement it. Results go to `results_02_20261103/`.

## Inputs

| Input | Location | Fixed by |
|---|---|---|
| OpenRouter list prices, including cache read, cache write and batch variants | `inputs_openrouter/models_2026-11-03.json` | sha256 in `inputs_sha256.txt` |
| OpenRouter published figures (cache rates, token mix, version lag) | `sources_02.md`, hand-copied with URL and date | quoted text |
| Epoch benchmark data, 2026-11-03 download | iMac `inputs_external/epoch/`, zip sha256 recorded by script 04 | script 04 |
| LMArena arena-human-preference-140k | iMac `inputs_external/arena/`, seven parquet files, sha256 recorded by script 06 | script 06 |
| OpenRouter weekly tokens and prices | iMac `instances/openrouter/data/normalized/` | round 01 |
| Session cost by turn range | iMac `raw/session_cost/2026-10-27/` | round 01 |

## Script 03: cache lever

Bill per million tokens as a function of the cache rate c, for the published agent mix (87% cached-eligible prompt, 12% novel prompt, 1% output, from Inferred 03) and the human mix (prompt 88%, output and reasoning 12%, with cache-eligible share treated as the variable). Prices from the snapshot for Claude Sonnet 5.5, Opus 5.5, Fable 5.1, GPT-6 Luna, GPT-6.1 Sol, Gemini 3.8 Flash and DeepSeek V4.1 Flash. Cache writes are charged at the 5-minute multiplier on the novel prompt tokens that start a cached prefix; the plan treats every novel prompt token as a write, which overstates write cost and so understates savings.

Outputs: `cache_curve.csv` (model, c from 0 to 0.95 by 0.05, bill), `cache_savings.csv` (model, start c in {0.44, 0.60, 0.70}, end c in {0.88, 0.90}, saving). Primary number: Sonnet 5.5, 0.60 to 0.88, agent mix.

Internal check from session data: the ratio of median session cost across turn ranges for Claude Code and Codex. A cached session grows close to linearly with turns; an uncached session grows close to quadratically. Fit both and report which fits, as a check that OpenRouter's cache rates describe these tools.

## Script 04: effort lever

For every model with four or more effort levels on CursorBench (score, cost per task) or DeepSWE (Pass@1, 95% CI half-width, mean cost), find the cheapest effort whose score is within noise of the max-effort score. Noise: on DeepSWE, the published half-width of the max run; on CursorBench, which publishes no error, a fixed 0.02 margin, the same margin as plan 01. Report cost relative to max and relative to high. Also the cheapest effort within noise of high, since high is a common default.

Outputs: `effort_by_model.csv`, `effort_summary.csv` (median and range of the saving across models, by benchmark).

## Script 05: version lag lever

On `model_weekly` and `price_weekly`, for the last four complete weeks (2026-09-28 to 2026-10-25), group models by family using a hand-written table `families_02.csv` (family, model, release order). Tokens on any model that is not the newest in its family are "lagged". Counterfactual: lagged tokens at the newest model's blended price. Report lagged token share and spend change, overall and by family, next to OpenRouter's published request-based numbers.

Outputs: `version_lag.csv`, `version_lag_by_family.csv`.

## Script 06: routing lever

Pairs, each inside one lab so the vendor relationship stays fixed: claude-opus-4 vs claude-sonnet-4, claude-sonnet-4 vs claude-3-5-haiku, gemini-2.5-pro vs gemini-2.5-flash, o3 vs o4-mini, gpt-4.1 vs gpt-4.1-mini. For each pair, battles where model_a and model_b are the two members, both orders.

Oracle: share of battles where the cheap member wins or ties (tie and both_bad count as no loss). Router: logistic regression on TF-IDF of the first user turn plus is_code, five-fold cross-validated, predicting "cheap member does not lose". Policy at threshold t: route to cheap when predicted probability is at least t. For t from 0.5 to 0.95: share routed to cheap, share of all prompts where the routed answer lost to the expensive member, and spend saving using OpenRouter list prices for those models from `price_weekly` in the battle period with the dataset's own token mix left unmeasured, so saving is priced per prompt at the prompt-token price ratio only. The reported saving is the one at the largest t with a loss share at or under 5% of prompts.

Outputs: `routing_pairs.csv` (pair, battles, oracle no-loss share, router AUC, saving at 5% loss, routed share at 5% loss), `routing_curves.csv`.

## Script 07: company simulation

10,000 simulated companies. Each draws:

- Workload split: agent share of tokens from Uniform(0.3, 0.9); agent mix 87/12/1 and human mix 50/38/12 (cache-eligible prompt, novel prompt, output) as in script 03.
- Starting cache rate: agent work from Uniform(0.44, 0.80), the January 2026 provider range in Inferred 03; human work half of that. Target after the lever: 0.88 agent, 0.60 human.
- Model: one of the seven models in script 03, equal probability.
- Effort: starting effort max with probability 0.25, high 0.5, medium 0.25; the lever moves to the cheapest within-noise effort from script 04 for that model where measured, otherwise no change.
- Version lag: share of tokens on a superseded version from Uniform(0, 0.5) with the family's published cost change from Inferred 05, where that family is in the table, otherwise no change.
- Batch share: share of tokens that can wait a day from Uniform(0, 0.3), at the published 50% discount.

Levers apply in this order: version, effort, cache, batch. Each company's saving is 1 minus the final bill over the starting bill. Report the distribution (percentiles 10, 25, 50, 75, 90), the share at or past 50%, and the saving with each lever removed in turn (attribution). Seed 20261103.

Outputs: `simulation_companies.csv`, `simulation_summary.csv`, `simulation_attribution.csv`.

## Decision rule

The rationale's table applies. Uninformative conditions: script 04 needs at least five models with four effort levels per benchmark; script 06 needs at least 500 battles per pair; script 05 needs families covering at least 40% of window tokens.

## Run

All five scripts run on the iMac at `/Volumes/PsychDynamicsData/workcast_spend/spend_reduction_20261103`, read-only against the data, no paid API calls. `run_02.sh` runs them in order. Results and `provenance_manifest_02.md` are copied back and committed the same day.
