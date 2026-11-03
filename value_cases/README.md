# Worked value case (sealed)

Client copy for the illustrative 3,000-employee value case, with every printed figure traceable to a hashed source.

- `out/value_cases_client.md`: the copy. Rendered; do not edit by hand. Edit `copy_template.md` (text) or
  `assumptions.yaml` (client example values), then run `./run_all.sh`.
- `out/PROVENANCE.md`: every printed figure, its formula, and the sealed inputs behind it (file, SHA-256, locator).
- `sealed/inputs.csv`: figures read from the sources. `sealed/case_numbers.csv`: every figure the copy prints.
- `sources/internal/`: copies of the repository results cited (Trip.com and purchase-to-pay validation, the OpenRouter
  evaluation, two instance files) with `manifest.json` hashes. `sources/external/<date>/`: snapshots of the cited
  public pages (Gallup, BLS data API, Microsoft) with `manifest.json` hashes.

Chain: `01_fetch_sources.sh` (external snapshots) → `02_snapshot_internal.sh` (repository results) →
`03_extract_inputs.py` (checks every hash, then reads each cited value) → `04_compute_cases.py` (every printed figure,
from inputs and assumptions) → `05_render_copy.py` (prints only sealed figures; fails on any other digit).

Sourced facts and illustrative assumptions are kept apart: anything a client's own figures replace is in
`assumptions.yaml`, and `out/PROVENANCE.md` labels it as an assumption.
