#!/usr/bin/env bash
# Anchor every forecast record's SHA-256 in the Bitcoin blockchain via OpenTimestamps (only the hash leaves the machine),
# and upgrade earlier stamps to complete proofs once their block is confirmed. Proofs sit next to each record as .ots.
set -euo pipefail
records="$1"
ots="${OTS:-ots}"
find "$records" -name '*.json' | while read -r f; do
  if [ ! -f "$f.ots" ]; then "$ots" stamp "$f" && echo "stamped $f"; fi
done
find "$records" -name '*.json.ots' | while read -r p; do "$ots" upgrade "$p" >/dev/null 2>&1 || true; done
