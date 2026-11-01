#!/usr/bin/env bash
# Weekly cycle of the forecast board (started over SSH by board/publish_from_laptop.sh; forecasts only when a new complete week is published):
# refresh the OpenRouter data, ingest, write this week's forecast if new, timestamp it, score all forecasts, build the page.
set -euo pipefail
cd "$(dirname "$0")/.."
BOARD=/Volumes/PsychDynamicsData/workcast_board
mkdir -p "$BOARD/records" "$BOARD/logs"
export BOARD_CODE_COMMIT="$(cat board/CODE_COMMIT 2>/dev/null || echo unknown)"
bash ~/bin/ensure_psychdynamics_mounted.sh >/dev/null 2>&1 || true
.venv/bin/python instances/openrouter/ingest/audit/fetch.py --only rankings,apps,live --refresh-days 10 --budget 120
.venv/bin/orgsim ingest openrouter
# the forecast step asks GPT-6 Astra (key from the iMac credential broker; published without Astra if unavailable)
.venv/bin/python /Volumes/PsychDynamicsData/workcast_ops/with_openai_key.py .venv/bin/python board/forecast_openrouter.py --records "$BOARD/records" \
  || .venv/bin/python board/forecast_openrouter.py --records "$BOARD/records"
OTS="$BOARD/.otsvenv/bin/ots" bash board/stamp.sh "$BOARD/records"
.venv/bin/python board/score_openrouter.py --records "$BOARD/records"
.venv/bin/python board/chart_data.py --market "$BOARD/market.json" || echo "market series not refreshed"
.venv/bin/python board/build_site.py --records "$BOARD/records" --out "$BOARD/site" --retro board/results/charts_retro.json --market "$BOARD/market.json"
