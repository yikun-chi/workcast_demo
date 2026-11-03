#!/usr/bin/env bash
# Snapshot the external pages the value cases cite, so each cited figure can be re-read from a hashed local copy.
# Writes sources/external/<name>.html and sources/external/manifest.json (url, retrieved_utc, bytes, sha256).
# Re-running fetches fresh copies into a new dated folder; earlier snapshots are kept.
set -euo pipefail
cd "$(dirname "$0")"
stamp=$(date -u +%Y-%m-%d)
out="sources/external/$stamp"
mkdir -p "$out"
ua="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
fetch() {   # name ext url
  curl -sSL --max-time 90 -A "$ua" -H "Accept-Language: en-US" -o "$out/$1.$2" "$3"
  printf '%s\t%s\t%s\n' "$1" "$2" "$3" >> "$out/urls.tsv"
}
: > "$out/urls.tsv"
fetch gallup_replacement_cost html https://www.gallup.com/workplace/247391/fixable-problem-costs-businesses-trillion.aspx
# BLS blocks scripted page downloads; the BLS data API serves the same OEWS figure the Occupational Outlook page quotes
# (national annual median wage, occupation 43-3031 bookkeeping, accounting and auditing clerks; data type 13 = annual median)
fetch bls_oews_433031_median json https://api.bls.gov/publicAPI/v1/timeseries/data/OEUN000000000000043303113
# the pricing page renders prices with JavaScript; Microsoft's pricing announcement states the list price in its text
fetch microsoft_copilot_pricing_announcement html https://blogs.microsoft.com/blog/2023/07/18/furthering-our-ai-ambitions-announcing-bing-chat-enterprise-and-microsoft-365-copilot-pricing/
fetch microsoft_learn_ptu_reservations html https://learn.microsoft.com/en-us/azure/cost-management-billing/reservations/azure-openai
python3 - "$out" <<'PY'
import hashlib, json, sys, datetime
from pathlib import Path
out = Path(sys.argv[1])
rows = [l.split("\t") for l in (out / "urls.tsv").read_text().splitlines() if l]
man = [{"file": f"{n}.{e}", "url": u, "retrieved_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "bytes": (out / f"{n}.{e}").stat().st_size, "sha256": hashlib.sha256((out / f"{n}.{e}").read_bytes()).hexdigest()} for n, e, u in rows]
(out / "manifest.json").write_text(json.dumps(man, indent=1))
for m in man:
    print(m["file"], m["bytes"], m["sha256"][:12])
PY
