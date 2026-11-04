#!/usr/bin/env bash
# Plan 03: run scripts 08 and 09 on the laptop, record input hashes and write the provenance manifest.
# Usage: ./run_03.sh   (from analyses/spend_reduction_20261103)
set -euo pipefail
cd "$(dirname "$0")"
OUT=results_03_20261104
mkdir -p "$OUT"
( cd inputs_03 && find . -type f ! -name 'inputs_03_sha256.txt' -print0 | sort -z | xargs -0 shasum -a 256 ) > inputs_03/inputs_03_sha256.txt
python3 08_usage_file_levers.py 2>&1 | tee "$OUT/log_08.txt"
python3 09_cascade_swebench.py 2>&1 | tee "$OUT/log_09.txt"
cat > "$OUT/provenance_manifest_03.md" <<EOF
# Provenance, plan 03 results

| Output | Script | Inputs |
|---|---|---|
| usage_summary.csv, usage_by_month.csv, usage_by_model.csv, levers_file.csv, levers_by_month.csv, session_distribution.csv, results_summary_08.md | \`../08_usage_file_levers.py\` | laptop \`~/.claude/projects/**/*.jsonl\` and \`~/.claude-harvard/projects/**/*.jsonl\` (read-only, counts and date range in usage_summary.csv); \`../inputs_openrouter/models_2026-11-03.json\` (sha256 in \`../inputs_sha256.txt\`); \`../inputs_03/anthropic_prices_latest_week.csv\` (sha256 in \`../inputs_03/inputs_03_sha256.txt\`) |
| cascade_pairs.csv, cascade_chains.csv, cascade_summary.csv, models_used.csv, results_summary_09.md | \`../09_cascade_swebench.py\` | \`../inputs_03/swebench/*/{metadata.yaml,per_instance_details.json}\` from github.com/SWE-bench/experiments, downloaded 2026-11-04 (sha256 in \`../inputs_03/inputs_03_sha256.txt\`) |

Run: \`./run_03.sh\` on the laptop, $(date -u +%Y-%m-%dT%H:%M:%SZ). Python $(python3 -c 'import sys,pandas; print(sys.version.split()[0], "pandas", pandas.__version__)'). No paid API calls. No prompt text, path or session identifier is written.
EOF
echo "done: $OUT"
