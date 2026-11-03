# Worked value cases

Financial illustrations for an assumed company, with each printed figure traceable
to a hashed source. These are not observed client savings. The sealed inputs are
snapshots and can differ from this checkout's latest evaluations; use the
[instance validation pages](../docs/README.md#instance-evidence) for current
simulation evidence and its limitations.

- `out/value_cases_client.md`: the copy. Rendered; do not edit by hand. Edit `copy_template.md` (text) or
  `assumptions.yaml` (client example values), then run `./value_cases/run_all.sh` from the repository root.
- `out/PROVENANCE.md`: every printed figure, its formula, and the sealed inputs behind it (file, SHA-256, locator).
- `sealed/inputs.csv`: figures read from the sources. `sealed/case_numbers.csv`: every figure the copy prints.
- `sources/internal/`: copies of cited validation pages, instance configuration and
  evaluations, with `manifest.json` hashes. `sources/external/<date>/`: snapshots of the cited
  public pages (Gallup, BLS data API, Microsoft) with `manifest.json` hashes.

## Rebuild and refresh

After the repository's normal `uv sync`, rebuild from the committed snapshots
without remote access:

```bash
./value_cases/run_all.sh
```

The default does not replace the source snapshots. It runs `03_extract_inputs.py`
(verify hashes and extract values), `04_compute_cases.py` (compute from inputs and
assumptions), and `05_render_copy.py` (render only sealed figures).

To use newly evaluated results from this checkout:

```bash
./value_cases/run_all.sh --refresh-internal
```

This calls `02_snapshot_internal.sh` / `snapshot_internal.py`. It requires the local
OpenRouter, Ctrip, BTOS and Stack Overflow evaluations plus the generated Trip.com
and procurement validation page. All required sources are checked before any
snapshot is replaced. Source paths and hashes are recorded in the manifest; no
SSH host or second platform checkout is used.

`--refetch` explicitly retrieves new external pages through `01_fetch_sources.sh`.
It can be combined with `--refresh-internal`. Review changes to the manifests,
sealed numbers and rendered copy before publishing refreshed illustrations.
Existing source snapshots retain their original text and hashes; relative links
inside copied documents refer to their original location under `docs/`.

Sourced facts and illustrative assumptions are kept apart: anything a client's own figures replace is in
`assumptions.yaml`, and `out/PROVENANCE.md` labels it as an assumption.
