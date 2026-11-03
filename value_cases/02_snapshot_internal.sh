#!/usr/bin/env bash
# Explicitly refresh the sealed internal sources from this checkout's local results.
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
exec "$repo/.venv/bin/python" "$repo/value_cases/snapshot_internal.py"
