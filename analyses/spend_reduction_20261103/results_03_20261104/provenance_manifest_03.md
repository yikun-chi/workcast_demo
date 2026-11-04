# Provenance, plan 03 results

| Output | Script | Inputs |
|---|---|---|
| usage_summary.csv, usage_by_month.csv, usage_by_model.csv, levers_file.csv, levers_by_month.csv, session_distribution.csv, results_summary_08.md | `../08_usage_file_levers.py` | laptop `~/.claude/projects/**/*.jsonl` and `~/.claude-harvard/projects/**/*.jsonl` (read-only, counts and date range in usage_summary.csv); `../inputs_openrouter/models_2026-11-03.json` (sha256 in `../inputs_sha256.txt`); `../inputs_03/anthropic_prices_latest_week.csv` (sha256 in `../inputs_03/inputs_03_sha256.txt`) |
| cascade_pairs.csv, cascade_chains.csv, cascade_summary.csv, models_used.csv, results_summary_09.md | `../09_cascade_swebench.py` | `../inputs_03/swebench/*/{metadata.yaml,per_instance_details.json}` from github.com/SWE-bench/experiments, downloaded 2026-11-04 (sha256 in `../inputs_03/inputs_03_sha256.txt`) |

Run: `./run_03.sh` on the laptop, 2026-11-04T07:20:04Z. Python 3.9.6 pandas 2.2.3. No paid API calls. No prompt text, path or session identifier is written.
