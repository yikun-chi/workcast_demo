#!/bin/bash
# Plan 02 runner. Run on the iMac from the analysis directory copy.
# Usage: ./run_02.sh [data_dir] [external_dir]
set -euo pipefail
cd "$(dirname "$0")"
DATA="${1:-/Volumes/PsychDynamicsData/workcast_demo/instances/openrouter/data}"
EXT="${2:-/Volumes/PsychDynamicsData/workcast_spend/spend_reduction_20261103/inputs_external}"
mkdir -p results_02_20261103
python3 03_cache_lever.py --data "$DATA" 2>&1 | tee results_02_20261103/log_03.txt
python3 04_effort_lever.py --epoch "$EXT/epoch" 2>&1 | tee results_02_20261103/log_04.txt
python3 05_version_lag_lever.py --data "$DATA" 2>&1 | tee results_02_20261103/log_05.txt
python3 06_routing_arena.py --arena "$EXT/arena" --data "$DATA" 2>&1 | tee results_02_20261103/log_06.txt
python3 06_routing_arena.py --arena "$EXT/arena" --data "$DATA" --min-battles 100 --suffix _exploratory_min100 2>&1 | tee results_02_20261103/log_06_exploratory.txt
python3 07_company_simulation.py 2>&1 | tee results_02_20261103/log_07.txt
