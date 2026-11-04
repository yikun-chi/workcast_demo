# Rationale 02: which lever halves a company's token bill at the same output quality?

Written 2026-11-03, after plan 01 returned 12.9% and before any lever below was computed.

## Question

Plan 01 tested one lever, switching models at equal benchmark scores, and found 12.9%. Sumer's instruction on 2026-11-03: go all out and find a way that simulation can cut a company's token bill by half. So the question changes. A company's bill is a product of five things: which model, which version of that model, how hard the model thinks, what share of prompt tokens are cache reads, and whether the work waits for a batch window. Plan 01 moved only the first. This round measures each of the other four from public data, then asks which combination reaches 50% while the model's outputs stay the same or the benchmark score stays within noise.

## Public facts that motivate the round

Read on 2026-11-03, quoted in `sources_02.md`.

- OpenRouter, Inferred 03 (2026-10-08): cached prompt tokens were "closer to 60%" of agent prompt tokens in January 2026 and "just under 90%" in September. The median provider cached 44% in January and 85% in September. Their worked example on Claude Sonnet 5: one million agent tokens cost about $0.51 cached and about $2.08 uncached, "four times as much".
- Anthropic and OpenAI docs: cache reads cost 0.1x of input on most models, 0.05x on the newest, 0.025x on Claude Fable 5.1. Anthropic Messages API caching needs a `cache_control` field. OpenAI caching is on by default, with illustrative hit rates of about 70% single-turn and over 90% multi-turn.
- OpenRouter, Inferred 05 (2026-10-23): 24% of requests and 23% of spend run on a superseded version; 30% of accounts touched one. Moving to the latest in-family version would cost 90% less for Haiku 4.5, 55% less for GPT-5.6 Sol, 36% less for Sonnet 4.6, 33% less for Opus 5, and more for Kimi, Grok and DeepSeek.
- Epoch AI, CursorBench and DeepSWE: the same model at five reasoning efforts, with score and cost per task. Claude Opus 5.5 scores 0.560 at high ($3.97 a task) and 0.578 at max ($13.43).
- Vendor pages, read on 2026-11-03 in round 01: Anthropic, OpenAI and Google each sell a 50% batch discount on the same model.
- LMArena, arena-human-preference-140k: 135,634 per-prompt battles with a human winner, April to July 2025.

## Working hypotheses

Each hypothesis names the lever that carries a company from its bill today to half of that bill, with outputs unchanged or benchmark scores within noise.

- **H-cache.** The cache rate does. A company at the January 2026 market norm pays about twice what the same tokens cost at today's agent norm. Simulation of session timing against the cache lifetime is what a product needs, so this is the lever a world model of the organization can sell.
- **H-effort.** Thinking budget does. Companies that run the default or maximum effort pay for score they never receive. The cheapest effort within benchmark noise costs under half of max.
- **H-version.** Version lag does. Companies on a superseded version of their own model family pay 33% to 90% more than the latest version.
- **H-route.** Per-prompt routing does. On most prompts a cheaper sibling model ties or wins, and a router can tell which.
- **H-stack.** No single lever does, and only the product of several reaches 50%.
- **H-none.** No public lever and no stack reaches 50% without a benchmark loss. The site then stays where plan 01 left it.

Routing and cross-vendor substitution change which model answers, so a benchmark can show a loss. Cache, batch and version carry the same model and either identical outputs (cache, batch) or a vendor's successor (version). The decision below keeps these two groups apart.

## The crucial tests

1. Cache: the bill as a function of the cache rate under published prices and OpenRouter's published agent token mix. The test reads off the saving from each documented starting point (44%, 60%, 70%) to the September agent norm (88% to 90%).
2. Effort: for each model with at least four effort levels on CursorBench or DeepSWE, the cheapest effort whose score is within noise of max, and its cost relative to max and to high.
3. Version: OpenRouter's published cost changes, plus our own token-weighted version of the same calculation on `model_weekly` and `price_weekly`.
4. Route: on arena battles within a model family, the oracle share of prompts where the cheap sibling ties or wins, and the share a text-only router recovers out of sample, with its quality cost.
5. Stack: a company simulation that draws token mix, starting cache rate, effort, version lag and batch share from the public ranges above and applies the levers in order. Output: the distribution of savings and the share of simulated companies at or past 50%.

## Decision table

| Result | Hypothesis left standing | What the site may say |
|---|---|---|
| A quality-neutral lever (cache, version, batch, within-noise effort) alone reaches 50% from a documented public starting point | that lever's hypothesis | "Cut your AI bill by up to 50% on the same models", with the lever named |
| No single lever reaches 50%, but the quality-neutral stack puts at least a quarter of simulated companies at or past 50% and the median at or past 35% | H-stack | "Up to 50%", with the stack described and the median shown |
| Only routing or cross-vendor switching gets there | H-route | A routing number with the measured quality cost, no "without losing" wording |
| Nothing reaches 50% | H-none | The plan 01 position |

## What these tests cannot settle

Productivity stays unmeasured. Cache and batch leave the model's outputs byte-identical, so the "without losing" phrase holds for those two levers at the level of outputs, and benchmark noise bounds the effort lever. No public dataset gives the starting cache rate, effort setting or version lag of any one enterprise. The simulation draws these from the public ranges, so the share of companies at 50% is a statement about those ranges, and a customer's own numbers replace them the moment a usage file is uploaded.
