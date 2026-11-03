# Public result snapshots

These JSON files are the data source for the public, read-only website. They contain
saved Results, scenarios, simulated interviews, aggregate summaries, table schemas,
ontology concepts and the data needed by the detailed result views. They exclude
individual input tables and full run traces.

Generate them from prepared local instances with:

```bash
uv run python scripts/export_site.py snapshot
```

Review and commit the changed JSON alongside the relevant source changes. The index
contains each instance file's checksum; the site build rejects mismatched files.
GitHub Actions builds from these committed snapshots without downloading datasets,
calling model APIs or running simulations.

Do not edit computed values manually. See [deployment and snapshots](../docs/setup.md#deployment)
for publishing and [agent.md](../agent.md) for file placement and evidence rules.
