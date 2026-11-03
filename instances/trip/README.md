# trip: Trip.com hybrid work-from-home experiment (workforce world)

Business problem, data, what is simulated, protocol and results: [validation](../../docs/validation.md).

- `manifests/sources.json`, `inventory_raw.json`, `reproduction.json`: provenance and the reproduction of the paper's
  headline numbers from the deposit (Harvard Dataverse doi:10.7910/DVN/6X4ZZL, CC BY 4.0)
- `ingest/run.py` (+ `ingest/audit/`): deposit -> `data/normalized/population.parquet`, `teams.parquet`,
  `reference_outcomes.json`, `summary.json`
- `ontology/bindings.yaml`: divisions, the Shanghai office and home locations, three roles bound to O*NET, activities,
  systems, the hybrid policy, latent states
- `calibration/priors.yaml` (every parameter with a cited source) and `dynamics.yaml` (trait layer, latent-state
  equations, quit hazard)
- `scenarios/`: `baseline` (the experiment as run), `hybrid_for_all` (the alternative), and the `evaluation` scenario the
  scoring protocol uses (the baseline with a 10% sample of hourly work events, to keep 50-seed runs small)
- `evaluation/protocol.yaml`: 50 seeds, primary outcomes, baselines; `reports/build_report.py` -> `report.json`
- `ui/treatment-vs-control.html`: detailed view embedded in Insights evidence

`manifests/pre_policy.yaml` records the paper's 9.8% attrition rate for the Airfare and IT divisions in the preceding six months. This aggregate is distinct from the later office-only group's outcome. The download contains no individual pre-period departure history.

`evaluation/comparators.yaml` defines the simple two-day calculation and its source. It scales the earlier four-day study's approximate 50% retention benefit by offered days, an explicit assumption. The same calculation is used in evaluation, the page and the report; it never reads the later outcomes.

To update labels and comparison methods without changing saved simulation predictions, run `.venv/bin/python scripts/refresh_trip_presentation.py`, then the report and validation-document builders.

Download and installation instructions: [setup and reproduction](../../docs/setup.md).

The second alternative, `ai_assistant`, explores AI-assisted task effort with human review and correction. Configure it in Scenarios and select **Compare with current policy**, or run `uv run orgsim explore trip --scenario ai_assistant`. Results are stored separately in `runs/trip/explorations.json`; the existing accuracy evaluation is unchanged. See [AI modeling boundaries](../../docs/architecture.md#ai-assistance-as-an-exploratory-intervention).
