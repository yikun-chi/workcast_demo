# Provenance, plan 02 results

| Output | Script | Inputs |
|---|---|---|
| cache_curve.csv, cache_savings.csv, cache_prices_used.csv, cache_session_growth.csv | `../03_cache_lever.py` | `../inputs_openrouter/models_2026-11-03.json` (sha256 in `../inputs_sha256.txt`); iMac `instances/openrouter/data/raw/session_cost/2026-10-27/o0.json, o500.json`; token mixes from `../sources_02.md` |
| effort_by_model.csv, effort_summary.csv | `../04_effort_lever.py` | iMac `inputs_external/epoch/cursorbench_external.csv, deepswe_external.csv` from `benchmark_data.zip` (sha256 in `effort_inputs_sha256.txt`) |
| version_lag.csv, version_lag_by_family.csv | `../05_version_lag_lever.py` | iMac `instances/openrouter/data/normalized/model_weekly, price_weekly, models`; `../families_02.csv` |
| routing_pairs.csv, routing_curves.csv (and `_exploratory_min100` versions) | `../06_routing_arena.py` | iMac `inputs_external/arena/train-0000[0-6]-of-00007.parquet` (sha256 in `routing_inputs_sha256.txt`); `price_weekly` |
| simulation_*.csv | `../07_company_simulation.py` | `cache_prices_used.csv`, `effort_by_model.csv`, version changes typed from `../sources_02.md` |

Run: `./run_02.sh` on the iMac at `/Volumes/PsychDynamicsData/workcast_spend/spend_reduction_20261103`, 2026-11-03. Logs: `log_03.txt` to `log_07.txt`. Python 3 with pandas 2.3.3 and scikit-learn 1.6.1. Seeds: 20261103 in scripts 06 and 07. External downloads were made on 2026-11-03 from epoch.ai and huggingface.co; the OpenRouter data are read-only.
