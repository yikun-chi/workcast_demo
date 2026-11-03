# Public result snapshots

These JSON files are the data source for the public, read-only website. They contain
Insights comparisons, scenario summaries, saved-run results and simulated interviews, input schemas,
ontology concepts and the data needed by the detailed result views. They exclude
raw source archives and bulk evaluation ensembles. `tables/` contains all normalized input
records as compressed chunks; `runs/` holds one selected completed run per named
scenario (history, overview replay frames and saved event records). The Data tab browses input records;
Results browses saved simulation history. Both load records on demand, search/sort
the full selected table, and open every field of a selected row.

Generate them from prepared local instances with:

```bash
uv run python scripts/export_site.py snapshot
```

Review and commit the changed JSON, history resources and record chunks alongside the relevant source
changes. The index contains a checksum for every instance file and chunk; the site
build rejects mismatched or incomplete files.
GitHub Actions builds from these committed snapshots without downloading datasets,
calling model APIs or running simulations.

Do not edit computed values manually. See [deployment and snapshots](../docs/setup.md#deployment)
for publishing and [agent.md](../agent.md) for file placement and evidence rules.
