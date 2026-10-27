# Plan: token demand prediction instance (`instances/openrouter/`)

Drafted 2026-10-27. Status: Phase 1 built as `instances/openrouter/` (world type `market`); results in `docs/validation_openrouter.md`. Phases 2 and 3 not built.

## The pitch

"WORKCAST predicts where AI tokens go when a new model launches or a price changes."

This turns into three showcase claims, built in order:

1. **Track record.** On public OpenRouter data, the simulation predicts weekly token share after major model launches and price cuts, and does better than standard forecasts.
2. **Your token bill.** Give us your workforce and we estimate your monthly AI token use and spend by role, and how a rollout changes it.
3. **Called in advance.** We publish forecasts before upcoming launches and score them in public as the data arrives.

Claim 1 gives credibility. Claim 2 is the thing buyers pay for. Claim 3 is the strongest stage moment, because a forecast dated before the event cannot have been tuned to it.

## Data (all checked on 2026-10-27)

| Source | What it gives | Span | License |
|---|---|---|---|
| OpenRouter `GET /api/v1/datasets/rankings-daily` | Tokens (prompt + completion) per model per day, week or month: top 50 models plus one `other` row. Filters: `modality`, `context_bucket`, `category` (for example `programming`, `roleplay`), `language_type` | From 2025-01-01 | CC BY 4.0. Cite as "Source: OpenRouter (openrouter.ai/rankings), as of {as_of}." |
| OpenRouter `GET /api/v1/datasets/app-rankings` | Tokens and requests per app, with app category and subcategory (for example `cli-agent`, `ide-extension`) | From 2025-01-01 | CC BY 4.0 |
| OpenRouter `GET /api/v1/datasets/session-cost` | Median USD per session by harness, model and turn range (weekly snapshot) | Current window only | CC BY 4.0 |
| Wayback Machine snapshots of `openrouter.ai/api/v1/models` | Price per token, context length and creation date for every listed model | 22 monthly snapshots, 2025-01-17 to 2026-10-02 (from the Wayback index) | Public archive of a public API. Facts only |
| Anthropic Economic Index (Hugging Face `Anthropic/EconomicIndex`) | Share of Claude use per O*NET task and SOC group, automation vs augmentation. Newest release 2026-06-26 | Several releases | Data CC BY, code MIT |
| Epoch AI price and benchmark data | Model quality scores and price history for a quality covariate | Varies | CC BY |

Access and limits: the OpenRouter dataset endpoints need any valid OpenRouter API key, with 30 requests per minute per key and 500 per day per account. I did not check whether dataset calls are billed. All history fits within one day's quota.

Known limits of the data, to state on the page:
- Token counts use each provider's own tokenizer, so a token from one provider is not the same unit as a token from another. The predictions target **share within a model family and week-over-week change**, not raw cross-provider totals.
- Only the top 50 models per day are named. The rest sit in `other`.
- Free and paid variants of a model are separate slugs. Merge them in ingest and keep the split available.
- `category` and `language_type` data are sampled estimates at weekly grain.
- OpenRouter is one marketplace, not the whole market. The claim is "on OpenRouter".

Prior work to cite: Fradkin (2025), "Demand for LLMs: Descriptive Evidence on Substitution, Market Expansion, and Multihoming" (arXiv 2504.15440). It used OpenRouter data and found that new models are adopted fast and level off within weeks, that launches differ in how much they take from rivals vs grow the market, and that apps use several models at once. The OpenRouter + a16z "State of AI" report (Dec 2025, 100 trillion tokens) supplies market context.

## Phase 1: the scored instance

Follows the platform framing: observed before, then the change, then the actual outcome next to other predictions and the simulation, then one alternative.

**Instance card**
- `company`: "The LLM API market on OpenRouter"
- `problem`: "When a major model launches or cuts its price, where do the tokens go?"
- `scenarios`: `baseline` (the launch as it happened) and one alternative (below).

**Events (the "changes")**
Pick 4 to 6 events from the data, not by hand:
- *Launches*: models whose `created` date falls in the window and that reach the top 10 by weekly tokens within 4 weeks.
- *Price cuts*: price drops of 30% or more between consecutive monthly snapshots, for models already in the top 20.

Write the list to `scenarios/events.yaml` before the first scored run. This lets the page say "every major launch in the window, not a hand-picked few". That claim holds up when an investor asks.

**What is predicted (horizons of 1, 2, 4 and 8 weeks)**
- The new or repriced model's weekly token share.
- Share lost by the top 5 incumbents (substitution) vs growth in total tokens (market expansion).
- The same for the two largest categories (`programming`, `roleplay`).

**Other predictions (comparators)**
1. Carry forward: shares stay where they were the week before.
2. Trend: extend each model's 4-week trend.
3. Last comparable launch: copy the share path of the previous launch in the same tier.
4. Simple choice model: a logit on price and quality fitted on the before period, with no agents.

The simulation has to beat these on most outcomes to make the headline. The results table shows all four, as in `bpi19`.

**The simulation (new world type `market`)**
- **Agents (seats):** demand segments. A segment is a use-case category crossed with an app type (for example programming × CLI agent, roleplay × chat front end). Segment sizes come from `app-rankings` and the category split of `rankings-daily`.
- **Fixed traits per segment:** price sensitivity, quality sensitivity, switching inertia, and how many models it spreads across (multihoming). Fitted on the before period only.
- **Each week a segment reallocates its tokens** across the models the kernel offers.
- **The kernel owns** which models exist, their prices (Wayback snapshots), quality scores (Epoch), launch dates, and total demand growth.
- **Adoption** follows a fast rise that levels off within weeks, in line with Fradkin (2025).
- **Seats** are `rule` by default. An `llm` seat ("you run a coding-agent app; choose your model mix for this week given these prices and scores") is a config change in `policies/seats.yaml`. It is useful in the demo and optional for scoring.
- **Calibration** uses rolling cutoffs as in `bpi19`: fit on the weeks before each event, never on the weeks after it.

**The alternative**
"What if the launch price had been twice as high?" or "What if the leading incumbent had matched the price cut the same week?"

**Required check before the demo:** the alternative must move the headline outcome by more than run-to-run noise. The `bpi19` staffing alternative changes 14-day completion from 11.79% to 11.78%. A what-if that shows no change makes the product look broken. Add a test that fails when the baseline and alternative headlines fall within each other's seed intervals.

**Interviews**
Simulated segment agents explain their switching ("a coding-agent app moved 40% of its traffic because..."), labelled as simulated, as on the other instances.

## Phase 2: "your token bill" (scenario tool, not scored)

- **Inputs:** a workforce with roles bound to O*NET. Both existing instances already bind roles to O*NET codes (`trip`, for example `15-1252.00`; `bpi19`, for example `43-3031.00`).
- **Method:** for each role, AI use from the Anthropic Economic Index task shares × sessions per user × cost per session (`session-cost`, by harness and model) gives tokens and dollars per role per month.
- **Scenarios:**
  - roll out a coding agent to engineering;
  - move a team from a frontier model to an open-weight model;
  - apply the price path from Phase 1.
- **Showcase:** "Trip.com's 1,612 employees: estimated monthly AI token bill, and what happens under each rollout."
- **Label:** the page calls this a scenario estimate. No public enterprise token data exists to score it against, so it stays separate from the Phase 1 track record (repository rule 7: the two tracks stay separate).

## Phase 3: live forecast board

- A daily job pulls `rankings-daily`.
- When a new model appears or a price changes in the models API, the simulation writes a forecast for 1, 2, 4 and 8 weeks, with a timestamp and git hash.
- The board scores each forecast as the weeks arrive and keeps every one, including the misses.
- This is the only claim no reviewer can dismiss as hindsight, so it is worth starting early. Every week of delay is a week of track record lost.

## Build steps

| Step | Files | Notes |
|---|---|---|
| 1. Download and manifest | `scripts/download_data.py` (add `openrouter`), `instances/openrouter/manifests/sources.json` | Rankings by month and category, app rankings, the 22 Wayback model snapshots, with hash and `as_of` for each |
| 2. Ingest | `instances/openrouter/ingest/run.py` | Weekly model × category token panel, merged variants, price and launch table, `summary.json` |
| 3. Event list | `instances/openrouter/scenarios/events.yaml` | Generated by the rule above and committed before scoring |
| 4. World type | `orgsim/worlds/market.py`, registered in `orgsim/worlds/__init__.py` | `World`, `evaluate`, `results_view`. Weekly tick: the clock is hourly, so either step 168 ticks or add a coarser tick and update `docs/contracts.md` (it requires `clock.tick: 1h`) |
| 5. People and interviews | `orgsim/ontology/people.py`, `orgsim/insights/interview.py` | Segment builder and segment interview facts |
| 6. Instance files | `instance.yaml`, `ontology/bindings.yaml`, `policies/seats.yaml`, `calibration/`, `evaluation/protocol.yaml`, `reports/build_report.py` | Per `instances/_template` |
| 7. Tests | `tests/test_market.py` | No future weeks in calibration at any cutoff. Alternative moves the outcome. Shares sum to 1 |
| 8. Verify | `pytest`, the UI smoke harness, screenshots of `#/openrouter/results` | As in `CLAUDE.md`, "How to verify" |
| 9. Phase 2 | `orgsim/insights/token_bill.py` or a scenario type | After Phase 1 is scored |
| 10. Phase 3 | a scheduled job (iMac LaunchAgent) | Needs a decision on where forecasts are published |

## Cost

- Data: free apart from the OpenRouter key (billing for dataset calls not checked).
- Simulation with `rule` seats: no API spend, runs on the laptop.
- LLM seats: optional. Price it before any run, and name the key and model first.

## Decisions for Sumer

1. Is Yikun building the `market` world type, or are we, in his repo? This plan sits in his repo. His `CLAUDE.md` says do not commit unless asked.
2. Which OpenRouter account and key to use for the dataset calls.
3. Should Phase 3 start right away, before Phase 1 is finished, to start the clock on the advance track record?
4. Should the hero event be a launch or a price cut? Launches are better known. Price cuts tell the cost story buyers care about.

## Sources

- OpenRouter datasets API: https://openrouter.ai/docs/api/api-reference/datasets/daily-token-totals-for-top-50-models.md, https://openrouter.ai/docs/api/api-reference/datasets/top-apps-by-token-usage.md, https://openrouter.ai/docs/api/api-reference/datasets/cost-per-session-by-harness-and-model.md
- OpenRouter data page: https://openrouter.ai/data
- Wayback index of the models API: https://web.archive.org/cdx/search/cdx?url=openrouter.ai/api/v1/models
- Fradkin (2025): https://arxiv.org/abs/2504.15440
- State of AI (OpenRouter + a16z): https://openrouter.ai/assets/State-of-AI.pdf
- Anthropic Economic Index: https://huggingface.co/datasets/Anthropic/EconomicIndex
- Epoch AI price trends: https://epoch.ai/data-insights/llm-inference-price-trends
