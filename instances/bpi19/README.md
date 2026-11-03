# bpi19: procurement purchase-to-pay, BPI Challenge 2019 (process world)

Business problem, data, what is simulated, protocol and results: [validation](../../docs/validation.md).

Verify the current result with `.venv/bin/python scripts/check_bpi19_results.py`. This checks the calibration boundary and identity, observed-only Before section, matching scenario dates and seeds, and recomputes every reported business-outcome error from the saved predictions. It does not rerun or change the model.

- `manifests/sources.json`: the XES log (CC BY 4.0) with hash and size
- `ingest/run.py` (+ `ingest/audit/`: XES parsing, anomaly checks, user roles, `validate_cutoffs.py` validation harness)
  -> `data/normalized/events_clean.parquet`, `cases_clean.parquet`, `user_roles.csv`, `process_map.json`, `summary.json`
- `ontology/bindings.yaml`: four units, six roles bound to O*NET, 42 activities mapped to DWAs, ERP/SRM systems and
  capabilities, policies
- `calibration/fit.yaml` fixes the pre-policy fitting boundary; `process.json` is refitted through August 31 after January-June fitting and July-August model selection. `constraints_support.json` is a descriptive audit, not fitted input.
- `scenarios/`: `baseline` (as operated) and `no_expansion` (an approximation using every human role at 62.5% of
  its observed staffing; this uniform multiplier is a scenario assumption)
- `evaluation/protocol.yaml`: two actual-only windows before the September 2018 expansion and four prediction windows after it, three seeds, 14-day
  horizon, metrics and baselines, the measured change; `reports/build_report.py` -> `report.json`
- `ui/process-map.html`: detailed view embedded in Results

Download and installation instructions: [setup and reproduction](../../docs/setup.md).

The second alternative, `ai_assistant`, explores AI-assisted task effort with human review and correction. Configure it in Scenarios and select **Compare with current policy**, or run `uv run orgsim explore bpi19 --scenario ai_assistant`. Results are stored separately in `runs/bpi19/explorations.json`; the existing accuracy evaluation is unchanged. See [AI modeling boundaries](../../docs/architecture.md#ai-assistance-as-an-exploratory-intervention).
