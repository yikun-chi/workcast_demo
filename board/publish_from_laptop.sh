#!/usr/bin/env bash
# Publish the forecast board to sumervaid.com/predict (Cloudflare Pages project sumervaid-predict).
# The iMac builds the page; this laptop holds the Cloudflare login, so it pulls the page and deploys only when it changed.
set -euo pipefail
STAGE="$HOME/.workcast_board_publish"
mkdir -p "$STAGE"
rsync -a --delete lab:/Volumes/PsychDynamicsData/workcast_board/site/ "$STAGE/site.new/"
if [ -d "$STAGE/site" ] && diff -rq "$STAGE/site" "$STAGE/site.new" >/dev/null; then
  rm -rf "$STAGE/site.new"; echo "$(date -u +%FT%TZ) unchanged"; exit 0
fi
rm -rf "$STAGE/site" && mv "$STAGE/site.new" "$STAGE/site"
cd "$STAGE"                                   # a neutral directory, so no other project's functions/ get bundled
npx -y wrangler@4.152.0 pages deploy site --project-name sumervaid-predict --branch main --commit-dirty=true
echo "$(date -u +%FT%TZ) deployed"
