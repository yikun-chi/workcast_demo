# Public result snapshots

These JSON files are the data source for the public, read-only website. They contain
saved Results, scenarios, simulated interviews, aggregate summaries, input schemas,
ontology concepts and the data needed by the detailed result views. They exclude
raw source archives and full run traces. `tables/` contains all normalized input
records as compressed chunks, loaded on demand by the public Data viewer. Search
and sort cover the full selected table; selecting a row shows all its fields.

Generate them from prepared local instances with:

```bash
uv run python scripts/export_site.py snapshot
```

Review and commit the changed JSON and table chunks alongside the relevant source
changes. The index contains a checksum for every instance file and chunk; the site
build rejects mismatched or incomplete files.
GitHub Actions builds from these committed snapshots without downloading datasets,
calling model APIs or running simulations.

Do not edit computed values manually. See [deployment and snapshots](../docs/setup.md#deployment)
for publishing and [agent.md](../agent.md) for file placement and evidence rules.
