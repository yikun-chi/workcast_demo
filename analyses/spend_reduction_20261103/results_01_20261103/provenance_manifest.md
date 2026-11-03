# Provenance, results_01_20261103

| Output | Script | Inputs |
|---|---|---|
| savings_summary.csv, savings_by_week.csv, savings_by_incumbent.csv, replacement_pairs.csv, session_check.csv, results_summary.md | `../01_quality_matched_savings.py` | iMac `workcast_demo/instances/openrouter/data` (normalized/category_weekly, normalized/price_weekly, raw/session_cost/2026-10-27), `../mapping_01.csv`, `../inputs_epoch/*.csv` (hashes in `../inputs_sha256.txt`) |
| exploratory_recent_weeks.csv, exploratory_incumbents_50pct.csv | `../02_exploratory_recent_weeks.py` (exploratory) | savings_by_week.csv, savings_by_incumbent.csv |

Rerun: `python 01_quality_matched_savings.py --data <instances/openrouter/data>`. The iMac run lives at `/Volumes/PsychDynamicsData/workcast_spend/spend_reduction_20261103`.
