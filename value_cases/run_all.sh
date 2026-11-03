#!/usr/bin/env bash
# Rebuild from sealed snapshots. Source refresh is explicit and changes the evidence.
set -euo pipefail
cd "$(dirname "$0")"
refresh_internal=false
refetch=false
for arg in "$@"; do
  case "$arg" in
    --refresh-internal) refresh_internal=true ;;
    --refetch) refetch=true ;;
    --help|-h)
      printf '%s\n' 'Usage: ./value_cases/run_all.sh [--refresh-internal] [--refetch]' \
        'Default: rebuild using the existing sealed snapshots, without network access.' \
        '--refresh-internal: copy results and reports from this checkout.' \
        '--refetch: retrieve new external source snapshots.'
      exit 0 ;;
    *) printf 'Unknown option: %s\n' "$arg" >&2; exit 2 ;;
  esac
done
if [[ ! -x ../.venv/bin/python ]]; then
  printf '%s\n' 'Run uv sync --locked --extra dev from the repository root first.' >&2
  exit 1
fi
if "$refresh_internal"; then ./02_snapshot_internal.sh; fi
if "$refetch"; then ./01_fetch_sources.sh; fi
../.venv/bin/python 03_extract_inputs.py
../.venv/bin/python 04_compute_cases.py
../.venv/bin/python 05_render_copy.py
