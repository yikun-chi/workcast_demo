# openrouter: AI token demand and spend

Companies are the apps OpenRouter ranks each week; the simulation predicts each one's tokens and spend at list prices
for eight weeks after a cutoff, and how its use-case segment's workloads move between models as models are listed and
prices change. Results: [docs/validation_openrouter.md](../../docs/validation_openrouter.md).

## Data

| Source | What | Licence |
|---|---|---|
| OpenRouter Datasets API (`rankings-daily`, `app-rankings`, `session-cost`) | tokens per model per day; tokens per app per week (ranks 1-200); use-case mixes; app categories | CC BY 4.0, "Source: OpenRouter (openrouter.ai/rankings), as of {as_of}" |
| Internet Archive captures of `openrouter.ai/api/v1/models` | list prices, creation dates | public API responses |
| Anthropic Economic Index, 1P API sample (pinned revision) | share and indexed tokens and cost per O*NET task; normalized to `aei_tasks.parquet` for the company token-bill estimate, not used by the simulation | CC BY (data) |

`python scripts/download_data.py openrouter --refresh` downloads to `data/raw/`
and writes `data/sources.local.json` with a SHA-256 per file, preserving the published
snapshot manifest. This retrieves new data rather than reproducing that snapshot byte for byte.
The OpenRouter calls need a key in
`OPENROUTER_API_KEY` or `~/.secrets/openrouter.key`; they are free and limited to 500 a day, and the fetch resumes where
it stopped. Then `orgsim ingest openrouter`, `orgsim evaluate openrouter`, `orgsim insights openrouter`,
`python instances/openrouter/reports/build_report.py` and `python scripts/build_openrouter_validation.py`.

The archived evaluation supplies prices and model launches after each prediction
date. App categories also use usage across the collected period. Until those inputs
are restricted by cutoff and the evaluation is rerun, its results must not be
described as predictions made entirely from information available beforehand.

## Files

- `calibration/market.yaml`: settings, the search grid for company dynamics, and the authored price sensitivity
- `scenarios/baseline.yaml`, `scenarios/leader_price_double.yaml` (alternative)
- `evaluation/protocol.yaml`: cutoffs, horizon, comparators, leakage rules
- `ingest/audit/probe_*.py`: development checks, not reported results
