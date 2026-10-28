#!/usr/bin/env bash
# Rebuild the sealed value-case copy. Pass --refetch to take new snapshots of the external pages first
# (a new dated folder; the latest folder is the one read).
set -euo pipefail
cd "$(dirname "$0")"
if [ "${1:-}" = "--refetch" ]; then ./01_fetch_sources.sh; fi
./02_snapshot_internal.sh
python3 03_extract_inputs.py
../.venv/bin/python 04_compute_cases.py
python3 05_render_copy.py
