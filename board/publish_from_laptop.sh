#!/usr/bin/env bash
# The scheduled job behind sumervaid.com/predict. Runs from the laptop because macOS blocks background jobs from the iMac's
# external drive and from ~/Documents here, while SSH reaches the drive. Install with board/install_laptop_job.sh, which
# copies this script out of ~/Documents.
# 1. the iMac refreshes the data, forecasts if a new week is complete, stamps, scores and builds the page
# 2. this laptop holds the Cloudflare login, so it pulls the page and deploys only when the page changed
set -uo pipefail
BOARD=/Volumes/PsychDynamicsData/workcast_board
echo "$(date -u +%FT%TZ) board run starts"
ssh -o ServerAliveInterval=30 lab "bash ~/bin/ensure_psychdynamics_mounted.sh >/dev/null 2>&1; /Volumes/PsychDynamicsData/workcast_demo/board/run_board.sh >> $BOARD/logs/board.log 2>&1" \
  && echo "$(date -u +%FT%TZ) board run ok" || echo "$(date -u +%FT%TZ) BOARD RUN FAILED: see $BOARD/logs/board.log on the iMac"
set -e
STAGE="$HOME/.workcast_board_publish"
mkdir -p "$STAGE"
rsync -a --delete lab:$BOARD/site/ "$STAGE/site.new/"
if [ -d "$STAGE/site" ] && diff -rq "$STAGE/site" "$STAGE/site.new" >/dev/null; then
  rm -rf "$STAGE/site.new"; echo "$(date -u +%FT%TZ) unchanged"; exit 0
fi
rm -rf "$STAGE/site" && mv "$STAGE/site.new" "$STAGE/site"
cd "$STAGE"                                   # a neutral directory, so no other project's functions/ get bundled
npx -y wrangler@4.152.0 pages deploy site --project-name sumervaid-predict --branch main --commit-dirty=true
echo "$(date -u +%FT%TZ) deployed"
