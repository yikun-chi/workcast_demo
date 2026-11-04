# Sources for plan 02, read on 2026-11-03

Each figure below was read from the named page on 2026-11-03 through WebFetch. Quotes are the page's words.

## OpenRouter, Inferred 03, "Cache is Crucial", 2026-10-08

https://openrouter.ai/data/newsletter/cache-is-crucial

- "Cache rate = cached prompt tokens / total prompt tokens."
- "In January, the cached share was closer to 60%."
- "Cached prompt tokens hovered just under 90% of all tokens used by agents in September."
- Models launched in Q3 2026 "averaged an 88.2% cache rate on agentic workloads," up from 54.8% for Q2 2025 launches.
- January: the median provider cached 44%; Google and Anthropic between 65% and 80%; 2 of 35 providers above 90%, both tiny. September: median provider 85%; 11 of 54 above 90%; DeepSeek near 96%.
- Humans: "novel prompt tokens are still the majority"; output and reasoning about 12% of tokens, against about 1% for agents.
- Claude Sonnet 5 example: $2 input, $10 output, $0.20 cached per million. One million agent tokens (about 87% cached, 12% novel prompt, 1% output) cost about $0.51; uncached about $2.08, "four times as much". The example ignores cache-write premiums.
- "Cached tokens are nearly nine in ten agentic tokens, but only about a third of the bill."
- Claude Opus 5.5 and GPT-6.1 Sol price cache reads at 1/20th of input; Claude Fable 5.1 at 1/200th of output.

## OpenRouter, Inferred 05, "Version lag", 2026-10-23, data 2026-10-15 to 21

https://openrouter.ai/data/newsletter/version-lag

- 24% of requests and 23% of spend went to an older version; 30% of active accounts sent at least one request to a superseded model. Only models in a version group are classified (about 48% of requests), so these are lower bounds.
- Older-version share of family requests: Claude Fable 17%, Claude Opus 20%, Claude Haiku 21%, GPT Sol 54%, Gemini Flash 60%, Grok 70%.
- Cost change at list prices if older-version traffic moved to the latest: Haiku 4.5 to 5.5, 90% less; GPT-5.6 Sol to latest, 55% less; Sonnet 4.6 to latest, 36% less; Opus 5 to latest, 33% less; Gemini 3.5 Flash to 3.8 Flash, 54% less; Kimi K2.6 to K3, 202% more; DeepSeek 0910 to V4.1 Flash, 151% more; Grok 4.3 to 4.7, 138% more; Gemini 3 Flash Preview to 3.8 Flash, 50% more.
- "Cost changes are not realized savings" because "output length and caching can change after a switch."

## OpenRouter, Inferred 04, "Model portfolios", 2026-10-15

https://openrouter.ai/data/newsletter/model-portfolios

- Large orgs used 12 models a month on average in September 2026 (median about 6); 66% of their requests go to the top model; 54% changed their top model in September.

## OpenRouter prompt caching docs

https://openrouter.ai/docs/features/prompt-caching

- Cache reads: Anthropic 0.1x, OpenAI 0.25x or 0.5x by model (older table), DeepSeek 0.1x, Gemini 0.25x, Qwen 0.1x. Writes: Anthropic 1.25x (5 min) and 2x (1 h); OpenAI 1.25x on GPT-5.6+; DeepSeek 1x; Gemini input plus storage.
- Minimum cacheable prompt: OpenAI 1,024 tokens; Anthropic 512 tokens on Claude 5.5 and later.
- The per-model snapshot in `inputs_openrouter/models_2026-11-03.json` supersedes the table where the two differ.

## Anthropic prompt caching docs

https://platform.claude.com/docs/en/docs/build-with-claude/prompt-caching

- "Cache write tokens with a 5-minute TTL are 1.25 times the base input tokens price." "Cache write tokens with a 1-hour TTL are 2 times the base input tokens price." "Cache read tokens are 0.1 times the base input tokens price."
- "Cache hits and refreshes on Claude Fable 5.1 and Claude Mythos 5.1 are priced at 0.025x the base input price." "Claude Opus 5.5 and Claude Sonnet 5.5 are priced at 0.05x."
- "By default, the cache has a 5-minute lifetime."
- Messages API: "Opt in with `cache_control`." Managed Agents: "Always on."

## OpenAI prompt caching docs

https://developers.openai.com/api/docs/guides/prompt-caching

- "Prompt caching is enabled by default for supported OpenAI models."
- GPT-5.6 and later: "Subsequent reads cost 0.1x the ordinary input rate on most of these models," 0.05x on GPT-6.1 Sol and Terra. Minimum 1,024 tokens. Lifetime 30 minutes or 12 hours.
- Illustrative hit rates: single-turn judge "~70%"; multi-turn agent ">90%". The page says these "illustrate a possible outcome".

## Epoch AI benchmark data

https://epoch.ai/data/benchmark_data.zip, CC BY 4.0, page dated updated 2026-11-03

- `cursorbench_external.csv`: Model version, Score, Reasoning level, Cost per task, Tokens per task.
- `deepswe_external.csv`: Model version, Pass@1, Reasoning effort, 95% CI half-width, Mean cost (USD), Mean output tokens.

## LMArena

https://huggingface.co/datasets/lmarena-ai/arena-human-preference-140k

- 135,634 rows, April 17 to July 24, 2025; columns include model_a, model_b, winner (model_a, model_b, tie, both_bad), conversation_a, is_code, category_tag. Prompts CC-BY-4.0.

## Batch discounts (round 01, read 2026-11-03)

- Anthropic claude.com/pricing, OpenAI platform.openai.com/docs/guides/batch, Google ai.google.dev/gemini-api/docs/batch-api: 50% off the same model for asynchronous work. The OpenRouter snapshot lists `:batch` variants at half price.
