# Plan 01: quality-matched savings

Status: every item below is fixed before the first savings number. Deviations go in `research_journal.md`.

## Data

| Source | Use | Licence |
|---|---|---|
| OpenRouter `category_weekly`, programming, read-only on the iMac | Tokens per model per week | CC BY 4.0 |
| `price_weekly` (Wayback list prices) | `blended_usd_mtok` per model per week | Public |
| OpenRouter `session-cost`, snapshot 2026-10-27 | Median session cost by harness, turn range and model | CC BY 4.0 |
| Epoch AI benchmark data, downloaded 2026-11-03 | FrontierCode main score, WebDev Arena score | CC BY 4.0 |

Window: the 26 weeks from 2026-04-27 to 2026-10-26. The first week after that is incomplete for model data.

## Quality score

`mapping_01.csv` links OpenRouter slugs to Epoch model versions by name, written before outcomes. A model's score on a benchmark is its maximum across listed effort settings. A dated re-release gets a score only where Epoch lists that date. Unmatched models keep their full spend, so they count as zero savings.

## Primary estimate

For each week and each incumbent model with both scores:

1. Candidates are models with tokens in that week's programming rows, a positive list price, both scores, and a score at or above the incumbent on **both** benchmarks.
2. Counterfactual price is the lowest candidate price, capped at the incumbent's own price.
3. Counterfactual spend = tokens x counterfactual price.

Primary saving = 1 - (sum of counterfactual spend) / (sum of actual spend), over all priced programming spend in the window. Token counts stay fixed.

## Pre-specified variants

Each one removes a specific objection.

- `same_vendor`: candidates from the incumbent's vendor only, for buyers who stay with one vendor.
- `us_vendors`: candidates from United States organizations only, for buyers who rule out other vendors.
- `margin`: candidate beats the incumbent by 0.02 on FrontierCode and by 25 Arena points, to reduce selection on benchmark noise.
- `frontiercode_only`: one benchmark, to show how much the second benchmark changes the result.

## Distribution, for the words "up to"

Report saving per incumbent, and the share of spend on incumbents saving at least 50%. "Up to 50%" requires a substantial share of spend at that level. Threshold: at least 25% of spend.

## Session check

Latest week, combining `o0` and `o500`. Within one harness and turn range, take the cheapest model that passes the dominance rule against the incumbent. Saving = 1 - cost(candidate) / cost(incumbent), weighted by the incumbent's latest-week programming spend.

## Inference

The result is a descriptive population figure for this marketplace, so no significance test applies. Stability is shown through the weekly range and the variants above.

## Known limits

Tokens follow each provider's tokenizer. List prices leave out caching and negotiated discounts. Benchmarks leave out latency, tool reliability, data residency and switching costs. Category tokens are sampled estimates at weekly grain. OpenRouter is one marketplace.

## Outputs, in `results_01_20261103/`

`savings_summary.csv`, `savings_by_week.csv`, `savings_by_incumbent.csv`, `replacement_pairs.csv`, `session_check.csv`, `results_summary.md`, `provenance_manifest.md`.

Exploratory only: anything beyond this plan, labeled as such in the journal.
